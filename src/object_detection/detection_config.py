import numpy as np

dataset_train_folder = '../../Training/'
dataset_test_folder = '../../Test/'

background_folder = '../../Dataset/Backgrounds/'
train_folder = '../../Dataset/Train/'
test_folder = '../../Dataset/Test/'
image_folder = train_folder + 'images/'
mask_folder = train_folder + 'masks/'
annotation_folder = train_folder + 'annotations/'
test_images = test_folder + 'images/'
test_annotations = test_folder + 'annotations/'
output_folder = '../../Dataset/Output/'
models_folder = 'models/'
labels_file = 'labels.txt'

################################ Dataset Generation ################################

with open(labels_file, mode='r') as f:
    fruit_labels = [x.strip() for x in f.readlines()]
fruit_labels.sort()
bg = 'Background'
fruit_labels = fruit_labels + [bg]
num_classes = len(fruit_labels)
class_to_color = {fruit_labels[v]: np.random.randint(0, 255, 3) for v in range(num_classes)}
color_map = {0: (0, 0, 0),
             1: (255, 255, 255)}

img_size = 640
img_shape = (img_size, img_size, 3)  # height, width, channels

# min/max width and height of images that are used to build the training data for each class
min_fruit_size = 60
max_fruit_size = 240

overlap_factor = 0.0

mask_threshold = 246  # threshold used for generating masks
# number of images to generate in the segmentation dataset
# for each generated image, the corresponding mask is also generated
# so the total number of generated images is 2 * dataset_generation_limit
dataset_generation_limit = 1000
# number of threads that build the dataset
# the load is balanced among the threads
total_threads = 1

################################# Training Parameters #################################
batch_size = 3
epochs = 200
input_shape_img = (None, None, 3)  # height, width, channels

# data augmentation
use_horizontal_flips = False
use_vertical_flips = False
random_rotate = False

# balanced_classes = True

# anchor box scales
anchor_box_scales = [64, 128, 256]
# anchor box ratios
anchor_box_ratios = [[1, 1], [1, 2], [2, 1]]
num_anchors = len(anchor_box_scales) * len(anchor_box_ratios)
# number of ROIs at once
# this should be determined based on the average number of objects per image as the training algorithm will try to feed roughly half positive and half negative samples
# if num_rois is too great compared to the number of objects in the image, most of the samples will represent background, thus the classifier will fail to train correctly
num_rois = 10
# stride at the RPN (this depends on the network configuration)
rpn_stride = 16

# img_channel_mean = [103.939, 116.779, 123.68]
# img_scaling_factor = 1.0
std_scaling = 4.0
classifier_regr_std = [8.0, 8.0, 4.0, 4.0]

# overlaps for RPN
rpn_min_overlap = 0.3
rpn_max_overlap = 0.7

# overlaps for classifier ROIs
classifier_min_overlap = 0.3
classifier_max_overlap = 0.7

# learning rates for rpn and classifier
initial_rpn_lr = 1e-1
min_rpn_lr = 1e-6
initial_cls_lr = 1e-1
min_cls_lr = 1e-6

########################################################################################
