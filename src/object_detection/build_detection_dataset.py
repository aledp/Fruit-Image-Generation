import math
import os
import threading

import numpy as np
import detection_config as config
import random
from PIL import Image, ImageEnhance, ImageDraw, ImageMath, ImageFilter
import xml.etree.ElementTree as ep


def build_dataset(thread_id, total_threads, limit, mutex, is_binary_mask=True, simple_annotation_format=True):
    bkg_image_paths = [config.background_folder + x for x in os.listdir(config.background_folder)]
    labels_to_images = {}

    mutex.acquire()
    try:
        if not os.path.exists(config.image_folder):
            os.makedirs(config.image_folder)
        if not os.path.exists(config.mask_folder):
            os.makedirs(config.mask_folder)
        if not os.path.exists(config.annotation_folder):
            os.makedirs(config.annotation_folder)
    finally:
        mutex.release()

    for i in range(0, len(config.fruit_labels) - 1):
        label = config.fruit_labels[i]
        img_paths = [config.dataset_train_folder + label + '/' + x for x in os.listdir(config.dataset_train_folder + label)]
        labels_to_images[label] = img_paths

    for index in range(limit):
        img_count = index * total_threads + thread_id
        canvas = Image.open(bkg_image_paths[random.randint(0, len(bkg_image_paths) - 1)]).resize(config.img_shape[:-1]).convert('RGB')
        canvas = enhance_image(canvas)
        canvas = np.array(canvas)
        mask_canvas = np.array(Image.new(mode='RGB', size=config.img_shape[:-1], color=(0, 0, 0)))
        anchors = []
        fruits_in_image = random.randint(1, 6)
        # fruits_in_image = 1
        for i in range(fruits_in_image):
            fruit_label_index = random.randint(0, len(config.fruit_labels) - 2)
            fruit_label = config.fruit_labels[fruit_label_index]
            fruit_image_path = labels_to_images[fruit_label][random.randint(0, len(labels_to_images[fruit_label]) - 1)]
            fruit_img_size = random.randint(config.min_fruit_size, config.max_fruit_size)
            rotate_angle = random.randint(0, 3) * 90
            fruit_image = Image.open(fruit_image_path).resize((fruit_img_size, fruit_img_size)).rotate(rotate_angle)
            fruit_mask = build_mask(fruit_image)
            if not is_binary_mask:
                fruit_mask = color_mask(fruit_mask, config.color_map[fruit_label_index])
            fruit_image = enhance_image(fruit_image)
            fruit_image = np.array(fruit_image)
            add_image_and_mask_to_canvas(canvas, fruit_image, mask_canvas, fruit_mask, anchors, fruit_label)
        canvas = Image.fromarray(canvas)
        mask_canvas = Image.fromarray(mask_canvas)
        canvas.save(config.image_folder + str(img_count) + '.png')
        mask_canvas.save(config.mask_folder + str(img_count) + '.png')
        write_annotation_to_file(anchors, img_count, simple_format=simple_annotation_format)
        print("Thread %d saved image %d.png" % (thread_id, img_count))


def write_annotation_to_file(anchors, img_count, simple_format=True):
    if simple_format:
        with open(config.annotation_folder + str(img_count), 'w') as f:
            f.write(str(img_count) + '.png\n')
            for anchor in anchors:
                f.write(str(anchor[0][0]) + ',' + str(anchor[0][1]) + ',' + str(anchor[3][0]) + ',' + str(anchor[3][1]) + ',' + anchor[4] + '\n')
    else:
        root = ep.Element('annotation')
        ep.SubElement(root, 'path').text = config.image_folder + str(img_count) + '.png'
        for anchor in anchors:
            obj = ep.SubElement(root, 'object')
            ep.SubElement(obj, 'name').text = anchor[4]
            bndbox = ep.SubElement(obj, 'bndbox')
            ep.SubElement(bndbox, 'xmin').text = str(anchor[0][0])
            ep.SubElement(bndbox, 'xmax').text = str(anchor[3][0])
            ep.SubElement(bndbox, 'ymin').text = str(anchor[0][1])
            ep.SubElement(bndbox, 'ymax').text = str(anchor[3][1])
        tree = ep.ElementTree(root)
        tree.write(file_or_filename=config.annotation_folder + str(img_count) + '.xml')


def enhance_image(canvas, sharpness=True, contrast=True, color=True, brightness=True):
    if sharpness:
        sharpness_enhancer = ImageEnhance.Sharpness(canvas)
        factor = random.random() * 0.6 + 0.7
        canvas = sharpness_enhancer.enhance(factor=factor)

    if contrast:
        contrast_enhancer = ImageEnhance.Contrast(canvas)
        factor = random.random() * 1.0 + 0.5
        canvas = contrast_enhancer.enhance(factor=factor)

    if color:
        color_enhancer = ImageEnhance.Color(canvas)
        factor = random.random() * 0.6 + 0.7
        canvas = color_enhancer.enhance(factor=factor)

    if brightness:
        brightness_enhancer = ImageEnhance.Brightness(canvas)
        factor = random.random() * 0.4 + 0.8
        canvas = brightness_enhancer.enhance(factor=factor)
    return canvas


# TODO: add partial occlusion
def add_image_and_mask_to_canvas(canvas, fruit_image, canvas_mask, fruit_mask, anchors, fruit_label):
    # bounds inside of which the fruit image can be added to the canvas
    # the fruit image could be partially outside of the canvas, to emulate the case where only part of the fruit is visible in an image
    # max_x = canvas.shape[0] - fruit_image.shape[0] // 2
    # max_y = canvas.shape[1] - fruit_image.shape[1] // 2
    # min_x = -fruit_image.shape[0]
    # min_y = -fruit_image.shape[1]
    max_x = canvas.shape[0] - fruit_image.shape[0] - 1
    max_y = canvas.shape[1] - fruit_image.shape[1] - 1
    min_x = 0
    min_y = 0
    x = 0
    y = 0
    done = False
    attempts = 10
    while not done and attempts > 0:
        # attempt to find a free area on the canvas to add the image
        # if no free space is found, the image is not added
        x = random.randint(min_x // 2, max_x)
        y = random.randint(min_y // 2, max_y)
        done = not is_overlap_between_new_image_and_old_images(((x, y), (x, y + fruit_image.shape[1]), (x + fruit_image.shape[0], y), (x + fruit_image.shape[0], y + fruit_image.shape[1])),
                                                               anchors)
        attempts -= 1
    if done:
        for i in range(fruit_image.shape[0]):
            for j in range(fruit_image.shape[1]):
                if 0 <= x + i < canvas.shape[0] and 0 <= y + j < canvas.shape[1]:
                    if (fruit_mask[i][j] == 255).all():
                        canvas[x + i][y + j] = fruit_image[i][j]
                        canvas_mask[x + i][y + j] = fruit_mask[i][j]
        # if the fruit is only partially included in the image, set the anchor bounds to the edge of the canvas
        upper_left = (max(x, 0), max(y, 0))
        lower_left = (max(x, 0), min(y + fruit_image.shape[1], canvas.shape[1] - 1))
        upper_right = (min(x + fruit_image.shape[0], canvas.shape[0] - 1), max(y, 0))
        lower_right = (min(x + fruit_image.shape[0], canvas.shape[0] - 1), min(y + fruit_image.shape[1], canvas.shape[1] - 1))
        anchors.append((upper_left, lower_left, upper_right, lower_right, fruit_label))
    return done


def is_overlap_between_new_image_and_old_images(img_coordinates, other_images):
    for old_img_coords in other_images:
        if is_src_img_inside_dest_img(img_coordinates, old_img_coords) or is_src_img_inside_dest_img(old_img_coords, img_coordinates):
            return True
    return False


def is_src_img_inside_dest_img(src_img_coordinates, dest_img_coordinates):
    upper_left_point = src_img_coordinates[0]
    upper_right_point = src_img_coordinates[1]
    lower_left_point = src_img_coordinates[2]
    lower_right_point = src_img_coordinates[3]

    height_upper_bound = dest_img_coordinates[0][0]  # as the upper left corner of an image is (0, 0), the upper bound will be smaller than the lower bound
    height_lower_bound = dest_img_coordinates[3][0]
    width_left_bound = dest_img_coordinates[0][1]
    width_right_bound = dest_img_coordinates[3][1]

    # set the coordinates lower for each image to allow some degree of overlap
    # source image
    factor = config.overlap_factor
    src_img_height = abs(upper_left_point[0] - lower_left_point[0])
    src_img_width = abs(upper_left_point[1] - upper_right_point[1])
    upper_left_point = (upper_left_point[0] + math.floor(src_img_height * factor), upper_left_point[1] + math.floor(src_img_width * factor))
    upper_right_point = (upper_right_point[0] + math.floor(src_img_height * factor), upper_right_point[1] - math.floor(src_img_width * factor))
    lower_left_point = (lower_left_point[0] - math.floor(src_img_height * factor), lower_left_point[1] + math.floor(src_img_width * factor))
    lower_right_point = (lower_right_point[0] - math.floor(src_img_height * factor), lower_right_point[1] - math.floor(src_img_width * factor))
    # destination image
    dest_img_height = abs(height_upper_bound - height_lower_bound)
    dest_img_width = abs(width_right_bound - width_left_bound)
    height_lower_bound -= math.floor(dest_img_height * factor)
    height_upper_bound += math.floor(dest_img_height * factor)
    width_left_bound += math.floor(dest_img_width * factor)
    width_right_bound -= math.floor(dest_img_width * factor)

    return ((height_upper_bound <= upper_left_point[0] <= height_lower_bound and width_left_bound <= upper_left_point[1] <= width_right_bound) or
            (height_upper_bound <= upper_right_point[0] <= height_lower_bound and width_left_bound <= upper_right_point[1] <= width_right_bound) or
            (height_upper_bound <= lower_left_point[0] <= height_lower_bound and width_left_bound <= lower_left_point[1] <= width_right_bound) or
            (height_upper_bound <= lower_right_point[0] <= height_lower_bound and width_left_bound <= lower_right_point[1] <= width_right_bound))


def build_mask(fruit_image, threshold=config.mask_threshold):
    fn = lambda x: 0 if x > threshold else 255
    inv_fn = lambda x: 0 if x == 255 else 255
    img = fruit_image.convert('L').point(fn, mode='1')
    img_copy = img.copy()
    x, y = fruit_image.size
    ImageDraw.floodfill(img_copy, xy=(0, 0), value=255)
    ImageDraw.floodfill(img_copy, xy=(x-1, 0), value=255)
    ImageDraw.floodfill(img_copy, xy=(0, y-1), value=255)
    ImageDraw.floodfill(img_copy, xy=(x-1, y-1), value=255)
    img_copy = img_copy.point(inv_fn, mode='1')
    img = ImageMath.eval("a | b", a=img, b=img_copy)
    img = img.convert('RGB')
    img = img.filter(ImageFilter.MinFilter(3))
    return np.array(img)


def color_mask(fruit_mask, fruit_mask_color):
    for i in range(fruit_mask.shape[0]):
        for j in range(fruit_mask.shape[1]):
            if (fruit_mask[i][j] == 255).all():
                fruit_mask[i][j] = fruit_mask_color
    return fruit_mask


if __name__ == "__main__":
    thrd_list = []
    mutex = threading.Lock()
    image_limit = config.dataset_generation_limit
    max_images_per_thread = int(math.ceil(image_limit / config.total_threads))
    for index in range(config.total_threads):
        thread = threading.Thread(target=build_dataset, args=(index, config.total_threads, min(max_images_per_thread, image_limit), mutex))
        image_limit -= max_images_per_thread
        thrd_list.append(thread)
        thread.start()

    for thrd in thrd_list:
        thrd.join()
