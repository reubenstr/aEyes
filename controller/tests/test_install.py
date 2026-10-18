"""Exercise installer selection and service generation without root or hardware."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


CONTROLLER = Path(__file__).resolve().parents[1]
INSTALLER = CONTROLLER / 'install.sh'
COMPONENTS = (
    'install_system_dependencies',
    'install_python_dependencies',
    'install_frontend_dependencies',
    'deploy_dashboard',
    'configure_oak_usb',
    'install_application_services',
    'install_shutdown_service',
    'configure_nginx',
    'configure_ethernet',
)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.installed = self.root / 'installed'
        self.installed.mkdir()

    def run_installer(self, answers='', args=(), real_components=(), extra_shell=''):
        shell = r'''
source "$1"
shift
setup_context() {
    echo CONTEXT
    USER_NAME=installer_test
    USER_HOME="$INSTALL_TEST_ROOT/home/test"
    ROOT_DIR="$INSTALL_SOURCE_ROOT"
    VENV_DIR="$INSTALL_TEST_ROOT/.venv"
    ETH_IP=192.168.5.100/24
    APT_UPDATED=false
    TASK_TMP=""
}
# Never invoke package managers, network configuration or service control.
apt() { echo "APT $*"; }
sudo() { echo "SUDO $*"; }
nmcli() { echo "Unexpected nmcli call" >&2; return 99; }
udevadm() { echo "Unexpected udevadm call" >&2; return 99; }
systemctl() { echo "SYSTEMCTL $*"; }
visudo() { echo "VISUDO $*"; }
install() {
    local source_file="${@: -2:1}" destination="${@: -1}"
    cp -- "$source_file" "$INSTALL_TEST_ROOT/installed/$(basename -- "$destination")"
    echo "INSTALL $*"
}
'''
        for component in COMPONENTS:
            if component not in real_components:
                shell += f'{component}() {{ echo "ACTION {component}"; }}\n'
        shell += extra_shell + '\nmain "$@"\n'
        return subprocess.run(
            ['bash', '-c', shell, 'installer-test', str(INSTALLER), *args],
            input=answers, text=True, capture_output=True, timeout=10,
            env={**os.environ, 'INSTALL_TEST_ROOT': str(self.root),
                 'INSTALL_SOURCE_ROOT': str(CONTROLLER)},
        )

    def actions(self, result):
        return [line.removeprefix('ACTION ') for line in result.stdout.splitlines()
                if line.startswith('ACTION ')]

    def select(self, *components):
        return '\n'.join(['n', *('y' if step in components else 'n' for step in COMPONENTS)]) + '\n'

    def test_each_component_can_run_without_other_components(self):
        for component in COMPONENTS:
            with self.subTest(component=component):
                result = self.run_installer(self.select(component))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.actions(result), [component])

    def test_declining_everything_and_default_answers_make_no_changes(self):
        for answers in (self.select(), '\n' * (len(COMPONENTS) + 1)):
            with self.subTest(answers=answers):
                result = self.run_installer(answers)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.actions(result), [])
                self.assertIn('Nothing changed', result.stdout)

    def test_interactive_all_and_all_flag_run_every_component(self):
        for answers, args in (('yes\n', ()), ('', ('--all',))):
            with self.subTest(args=args):
                result = self.run_installer(answers, args)
                self.assertEqual(result.returncode, 0, result.stderr)
                actions = self.actions(result)
                self.assertCountEqual(actions, COMPONENTS)
                self.assertLess(actions.index('install_system_dependencies'),
                                actions.index('install_python_dependencies'))
                self.assertLess(actions.index('install_frontend_dependencies'),
                                actions.index('deploy_dashboard'))
                self.assertEqual(actions[-1], 'configure_ethernet')

    def test_eof_cancels_before_any_selected_actions_run(self):
        for answers in ('', 'n\ny\n'):
            with self.subTest(answers=answers):
                result = self.run_installer(answers)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.actions(result), [])
                self.assertIn('cancelled before making changes', result.stderr)

    def test_invalid_answers_reprompt_and_yes_is_case_insensitive(self):
        result = self.run_installer('maybe\nYES\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Please answer yes or no', result.stdout)
        self.assertCountEqual(self.actions(result), COMPONENTS)

    def test_help_and_invalid_options_do_not_initialize_installation(self):
        for option, expected_code in (('--help', 0), ('--unknown', 2)):
            with self.subTest(option=option):
                result = self.run_installer(args=(option,))
                self.assertEqual(result.returncode, expected_code)
                self.assertNotIn('CONTEXT', result.stdout)
                self.assertEqual(self.actions(result), [])

    def test_python_dependencies_create_venv_and_install_as_deployment_user(self):
        result = self.run_installer(self.select('install_python_dependencies'),
                                    real_components=('install_python_dependencies',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SUDO -u installer_test python3 -m venv', result.stdout)
        self.assertIn('--system-site-packages', result.stdout)
        self.assertIn(f'{self.root}/.venv/bin/python -m pip install -r {CONTROLLER}/requirements.txt',
                      result.stdout)
        self.assertNotIn('APT ', result.stdout)
        self.assertNotIn('SYSTEMCTL ', result.stdout)

    def test_application_service_installation_renders_units_without_dependencies_or_startup(self):
        result = self.run_installer(self.select('install_application_services'),
                                    real_components=('install_application_services',))
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = (self.installed / 'main.service').read_text()
        self.assertIn('User=installer_test', unit)
        self.assertIn(f'WorkingDirectory="{CONTROLLER}"', unit)
        self.assertNotIn('@ROOT@', unit)
        monitor = (self.installed / 'aeyes-monitor.service').read_text()
        self.assertIn('-m monitoring --host 127.0.0.1 --port 8080', monitor)
        sudoers = (self.installed / 'aeyes-monitor').read_text()
        self.assertIn('installer_test ALL=(root) NOPASSWD: /usr/bin/systemctl restart main.service',
                      sudoers)
        self.assertIn('VISUDO -cf ', result.stdout)
        self.assertIn('INSTALL -m 0440 ', result.stdout)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('SYSTEMCTL ')],
                         ['SYSTEMCTL daemon-reload'])
        self.assertNotIn('APT ', result.stdout)
        self.assertFalse(any(line.startswith('SUDO ') for line in result.stdout.splitlines()))

    def test_shutdown_service_installation_does_not_enable_or_restart_it(self):
        result = self.run_installer(self.select('install_shutdown_service'),
                                    real_components=('install_shutdown_service',))
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = (self.installed / 'shutdown.service').read_text()
        self.assertIn(f'ExecStart="{CONTROLLER}/.venv/bin/python"', unit)
        self.assertIn(f'Environment="XAUTHORITY={self.root}/home/test/.Xauthority"', unit)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('SYSTEMCTL ')],
                         ['SYSTEMCTL daemon-reload'])
        self.assertNotIn('APT ', result.stdout)

    def test_system_dependencies_do_not_install_or_configure_nginx(self):
        result = self.run_installer(self.select('install_system_dependencies'),
                                    real_components=('install_system_dependencies',))
        self.assertEqual(result.returncode, 0, result.stderr)
        package_calls = [line for line in result.stdout.splitlines() if line.startswith('APT ')]
        self.assertEqual(package_calls[0], 'APT update')
        self.assertIn('python3-venv', package_calls[1])
        self.assertNotIn('nginx', package_calls[1])
        self.assertNotIn('SYSTEMCTL ', result.stdout)

    def test_ethernet_configuration_can_run_without_any_installations(self):
        result = self.run_installer(
            self.select('configure_ethernet'), real_components=('configure_ethernet',),
            extra_shell=r'''
nmcli() {
    if [ "$1" = -t ]; then
        echo 'Wired connection 1:eth0'
    else
        echo "NMCLI $*"
    fi
}
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NMCLI con mod Wired connection 1 ipv4.method manual ipv4.addresses 192.168.5.100/24',
                      result.stdout)
        self.assertIn('NMCLI con up Wired connection 1', result.stdout)
        self.assertNotIn('APT ', result.stdout)
        self.assertNotIn('SYSTEMCTL ', result.stdout)


if __name__ == '__main__':
    unittest.main()
