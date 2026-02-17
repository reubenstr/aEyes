# Controller

Captures camera data and sends commands to the eyes.

## Installation


Create bare repo
```bash
mkdir -p ~/git-remotes
git clone --bare git@gitlab.com:reubenstr/aEyes.git ~/git-remotes/aEyes.git
```

Clone from the bare repo
```bash
git clone ~/git-remotes/aEyes.git ~/aEyes
```

Push controller updates
```bash
cd ~/aEyes
git push origin main
```

Push all updates to the remote repo (Gitlab)
```bash
cd ~/git-remotes/aEyes.git
git push origin main
```



### MISC

sudo apt install -y python3-venv

python3 -m venv .venv

source .venv/bin/activate

pip install --upgrade pip

pip install pyzmq





