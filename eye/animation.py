import pygame
import os
import zmq
import time
import json
from PIL import Image

MEDIA_DIR = "media"
TARGET_SIZE = (1080, 1080)
ROTATE_STEP = 1 / 100

pygame.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()

SCREEN_W, SCREEN_H = screen.get_size()
CENTER_X = SCREEN_W // 2
CENTER_Y = SCREEN_H // 2


context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5555")
socket.setsockopt_string(zmq.SUBSCRIBE, "")


# Load images once (Pillow -> pygame surfaces)
surfaces = []

for fname in sorted(os.listdir(MEDIA_DIR)):
    if fname.lower().endswith((".png", ".jpg", ".jpeg")):
        path = os.path.join(MEDIA_DIR, fname)
        img = Image.open(path).convert("RGBA")
        img = img.resize(TARGET_SIZE, Image.LANCZOS)
        surface = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        surfaces.append(surface)

if len(surfaces) < 2:
    raise RuntimeError("Need at least two images in the media folder")

current_index = 0
rotation_angle = 0
running = True

while running:

    try:
        # Non-blocking receive
        raw_msg = socket.recv_string(flags=zmq.NOBLOCK)
        msg = json.loads(raw_msg) 
        print("Received:", msg)

        if 'rotation' in msg:
            rotation_angle = msg['rotation']          
        else:
            print("Message has no 'rotation':", msg)
    
    except zmq.Again:   
        pass
      


    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            # Exit keys
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

            # Switch images
            elif event.key == pygame.K_1:
                current_index = 0
                rotation_angle = 0  # reset rotation
            elif event.key == pygame.K_2:
                current_index = 1
                rotation_angle = 0  # reset rotation

            # Rotate
            elif event.key == pygame.K_LEFT:
                rotation_angle = (rotation_angle + ROTATE_STEP) % 360
            elif event.key == pygame.K_RIGHT:
                rotation_angle = (rotation_angle - ROTATE_STEP) % 360

    # Rotate the current image
    rotated_surface = pygame.transform.rotate(surfaces[current_index], rotation_angle)
    rotated_rect = rotated_surface.get_rect(center=(CENTER_X, CENTER_Y))

    # Draw
    screen.fill((0, 0, 0))
    screen.blit(rotated_surface, rotated_rect.topleft)
    pygame.display.flip()

    clock.tick(60)

pygame.quit()
