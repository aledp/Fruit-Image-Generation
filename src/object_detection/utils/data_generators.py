from __future__ import absolute_import
import numpy as np
import cv2
import random
import math
import detection_config
from tensorflow.keras.utils import Sequence
from utils import data_augment


def union(au, bu, area_intersection):
    area_a = (au[2] - au[0]) * (au[3] - au[1])
    area_b = (bu[2] - bu[0]) * (bu[3] - bu[1])
    area_union = area_a + area_b - area_intersection
    return area_union


def intersection(ai, bi):
    x = max(ai[0], bi[0])
    y = max(ai[1], bi[1])
    w = min(ai[2], bi[2]) - x
    h = min(ai[3], bi[3]) - y
    if w < 0 or h < 0:
        return 0
    return w * h


def iou(a, b):
    # a and b should be (x1,y1,x2,y2)

    if a[0] >= a[2] or a[1] >= a[3] or b[0] >= b[2] or b[1] >= b[3]:
        return 0.0

    area_i = intersection(a, b)
    area_u = union(a, b, area_i)

    return float(area_i) / float(area_u + 1e-6)


def get_new_img_size(width, height, img_min_side=detection_config.img_size):
    if width <= height:
        f = float(img_min_side) / width
        resized_height = int(f * height)
        resized_width = img_min_side
    else:
        f = float(img_min_side) / height
        resized_width = int(f * width)
        resized_height = img_min_side

    return resized_width, resized_height


def calc_rpn(img_data, width, height, resized_width, resized_height, img_length_calc_function):
    downscale = float(detection_config.rpn_stride)
    anchor_sizes = detection_config.anchor_box_scales
    anchor_ratios = detection_config.anchor_box_ratios
    num_anchors = detection_config.num_anchors

    # calculate the output map size based on the network architecture

    (output_width, output_height) = img_length_calc_function(resized_width, resized_height)

    n_anchratios = len(anchor_ratios)

    # initialise empty output objectives
    y_rpn_overlap = np.zeros((output_height, output_width, num_anchors)).astype(float)
    y_is_box_valid = np.zeros((output_height, output_width, num_anchors)).astype(float)
    y_rpn_regr = np.zeros((output_height, output_width, num_anchors * 4)).astype(float)

    num_bboxes = len(img_data['bboxes'])

    num_anchors_for_bbox = np.zeros(num_bboxes).astype(int)
    best_anchor_for_bbox = -1 * np.ones((num_bboxes, 4)).astype(int)
    best_iou_for_bbox = np.zeros(num_bboxes).astype(np.float32)
    best_x_for_bbox = np.zeros((num_bboxes, 4))
    best_dx_for_bbox = np.zeros((num_bboxes, 4))

    # get the GT box coordinates, and resize to account for image resizing
    gta = np.zeros((num_bboxes, 4))
    for bbox_num, bbox in enumerate(img_data['bboxes']):
        # get the GT box coordinates, and resize to account for image resizing
        gta[bbox_num, 0] = bbox['x1'] * (resized_width / float(width))
        gta[bbox_num, 1] = bbox['x2'] * (resized_width / float(width))
        gta[bbox_num, 2] = bbox['y1'] * (resized_height / float(height))
        gta[bbox_num, 3] = bbox['y2'] * (resized_height / float(height))

    # rpn ground truth

    for anchor_size_idx in range(len(anchor_sizes)):
        for anchor_ratio_idx in range(n_anchratios):
            anchor_x = anchor_sizes[anchor_size_idx] * anchor_ratios[anchor_ratio_idx][0]
            anchor_y = anchor_sizes[anchor_size_idx] * anchor_ratios[anchor_ratio_idx][1]

            for ix in range(output_width):
                # x-coordinates of the current anchor box
                x1_anc = downscale * (ix + 0.5) - anchor_x / 2
                x2_anc = downscale * (ix + 0.5) + anchor_x / 2

                # ignore boxes that go across image boundaries
                if x1_anc < 0 or x2_anc > resized_width:
                    continue

                for jy in range(output_height):

                    # y-coordinates of the current anchor box
                    y1_anc = downscale * (jy + 0.5) - anchor_y / 2
                    y2_anc = downscale * (jy + 0.5) + anchor_y / 2

                    # ignore boxes that go across image boundaries
                    if y1_anc < 0 or y2_anc > resized_height:
                        continue

                    # bbox_type indicates whether an anchor should be a target
                    bbox_type = 'neg'

                    # this is the best IOU for the (x,y) coord and the current anchor
                    # note that this is different from the best IOU for a GT bbox
                    best_iou_for_loc = 0.0
                    best_regr = [0, 0, 0, 0]

                    for bbox_num in range(num_bboxes):

                        # get IOU of the current GT box and the current anchor box
                        curr_iou = iou([gta[bbox_num, 0], gta[bbox_num, 2], gta[bbox_num, 1], gta[bbox_num, 3]], [x1_anc, y1_anc, x2_anc, y2_anc])
                        # calculate the regression targets if they will be needed
                        if curr_iou > best_iou_for_bbox[bbox_num] or curr_iou > detection_config.rpn_max_overlap:
                            cx = (gta[bbox_num, 0] + gta[bbox_num, 1]) / 2.0
                            cy = (gta[bbox_num, 2] + gta[bbox_num, 3]) / 2.0
                            cxa = (x1_anc + x2_anc) / 2.0
                            cya = (y1_anc + y2_anc) / 2.0

                            tx = (cx - cxa) / (x2_anc - x1_anc)
                            ty = (cy - cya) / (y2_anc - y1_anc)
                            # calculate log of tw and th later
                            tw = 1.0 * (gta[bbox_num, 1] - gta[bbox_num, 0]) / (x2_anc - x1_anc)
                            th = 1.0 * (gta[bbox_num, 3] - gta[bbox_num, 2]) / (y2_anc - y1_anc)

                        if detection_config.fruit_labels[img_data['bboxes'][bbox_num]['class']] != detection_config.bg:
                            # all GT boxes should be mapped to an anchor box, so we keep track of which anchor box was best
                            if curr_iou > best_iou_for_bbox[bbox_num]:
                                best_anchor_for_bbox[bbox_num] = [jy, ix, anchor_ratio_idx, anchor_size_idx]
                                best_iou_for_bbox[bbox_num] = curr_iou
                                best_x_for_bbox[bbox_num, :] = [x1_anc, x2_anc, y1_anc, y2_anc]
                                best_dx_for_bbox[bbox_num, :] = [tx, ty, tw, th]

                            # we set the anchor to positive if the IOU is >0.7 (it does not matter if there was another better box, it just indicates overlap)
                            if curr_iou > detection_config.rpn_max_overlap:
                                bbox_type = 'pos'
                                num_anchors_for_bbox[bbox_num] += 1
                                # we update the regression layer target if this IOU is the best for the current (x,y) and anchor position
                                if curr_iou > best_iou_for_loc:
                                    best_iou_for_loc = curr_iou
                                    best_regr = (tx, ty, tw, th)

                            # if the IOU is >0.3 and <0.7, it is ambiguous and no included in the objective
                            if detection_config.rpn_min_overlap < curr_iou < detection_config.rpn_max_overlap:
                                # gray zone between neg and pos
                                if bbox_type != 'pos':
                                    bbox_type = 'neutral'

                    # turn on or off outputs depending on IOUs
                    if bbox_type == 'neg':
                        y_is_box_valid[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 1
                        y_rpn_overlap[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 0
                    elif bbox_type == 'neutral':
                        y_is_box_valid[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 0
                        y_rpn_overlap[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 0
                    elif bbox_type == 'pos':
                        y_is_box_valid[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 1
                        y_rpn_overlap[jy, ix, anchor_ratio_idx + n_anchratios * anchor_size_idx] = 1
                        start = 4 * (anchor_ratio_idx + n_anchratios * anchor_size_idx)
                        y_rpn_regr[jy, ix, start:start + 2] = best_regr[0:2]
                        y_rpn_regr[jy, ix, start + 2:start + 4] = np.log(best_regr[2:])

    # we ensure that every bbox has at least one positive RPN region

    for idx in range(num_anchors_for_bbox.shape[0]):
        if num_anchors_for_bbox[idx] == 0:
            # no box with an IOU greater than zero ...
            if best_anchor_for_bbox[idx, 0] == -1:
                continue
            y_is_box_valid[best_anchor_for_bbox[idx, 0], best_anchor_for_bbox[idx, 1], best_anchor_for_bbox[idx, 2] + n_anchratios * best_anchor_for_bbox[idx, 3]] = 1
            y_rpn_overlap[best_anchor_for_bbox[idx, 0], best_anchor_for_bbox[idx, 1], best_anchor_for_bbox[idx, 2] + n_anchratios * best_anchor_for_bbox[idx, 3]] = 1
            start = 4 * (best_anchor_for_bbox[idx, 2] + n_anchratios * best_anchor_for_bbox[idx, 3])
            y_rpn_regr[best_anchor_for_bbox[idx, 0], best_anchor_for_bbox[idx, 1], start:start + 2] = best_dx_for_bbox[idx, 0:2]
            y_rpn_regr[best_anchor_for_bbox[idx, 0], best_anchor_for_bbox[idx, 1], start + 2:start + 4] = np.log(best_dx_for_bbox[idx, 2:4])

    y_rpn_overlap = np.transpose(y_rpn_overlap, (2, 0, 1))
    y_rpn_overlap = np.expand_dims(y_rpn_overlap, axis=0)

    y_is_box_valid = np.transpose(y_is_box_valid, (2, 0, 1))
    y_is_box_valid = np.expand_dims(y_is_box_valid, axis=0)

    y_rpn_regr = np.transpose(y_rpn_regr, (2, 0, 1))
    y_rpn_regr = np.expand_dims(y_rpn_regr, axis=0)

    pos_locs = np.where(np.logical_and(y_rpn_overlap[0, :, :, :] == 1, y_is_box_valid[0, :, :, :] == 1))
    neg_locs = np.where(np.logical_and(y_rpn_overlap[0, :, :, :] == 0, y_is_box_valid[0, :, :, :] == 1))

    num_pos = len(pos_locs[0])

    # one issue is that the RPN has many more negative than positive regions, so we turn off some of the negative
    # regions. We also limit it to 256 regions.
    num_regions = 256

    # use integer division as random.sample does not cast the result of num_regions / 2 to int, resulting in an error
    if len(pos_locs[0]) > num_regions // 2:
        val_locs = random.sample(range(len(pos_locs[0])), len(pos_locs[0]) - num_regions // 2)
        y_is_box_valid[0, pos_locs[0][val_locs], pos_locs[1][val_locs], pos_locs[2][val_locs]] = 0
        num_pos = num_regions // 2

    if len(neg_locs[0]) + num_pos > num_regions:
        val_locs = random.sample(range(len(neg_locs[0])), len(neg_locs[0]) - num_pos)
        y_is_box_valid[0, neg_locs[0][val_locs], neg_locs[1][val_locs], neg_locs[2][val_locs]] = 0

    y_rpn_cls = np.concatenate([y_is_box_valid, y_rpn_overlap], axis=1)
    y_rpn_regr = np.concatenate([np.repeat(y_rpn_overlap, 4, axis=1), y_rpn_regr], axis=1)

    return np.copy(y_rpn_cls), np.copy(y_rpn_regr)


def get_anchor_gt(all_img_data, img_length_calc_function, augment=True, shuffle=True):
    # The following line is not useful with Python 3.5, it is kept for the legacy
    # all_img_data = sorted(all_img_data)

    while True:
        if shuffle:
            np.random.shuffle(all_img_data)

        for img_data in all_img_data:
            try:
                # read in image, and optionally add augmentation
                height, width, resized_height, resized_width, img_data_aug, x_img = augment_and_resize_image(img_data, augment=augment)

                try:
                    y_rpn_cls, y_rpn_regr = calc_rpn(img_data_aug, width, height, resized_width, resized_height, img_length_calc_function)
                except:
                    continue

                x_img, y_rpn_cls, y_rpn_regr = arrange_dims(x_img, y_rpn_cls, y_rpn_regr)

                yield np.copy(x_img), [np.copy(y_rpn_cls), np.copy(y_rpn_regr)], img_data_aug

            except Exception as e:
                print(e)
                continue


class CustomDataGenerator(Sequence):
    def __init__(self, all_imgs, img_length_calc_function, batch_size=5, augment=True, shuffle=True):
        self.all_imgs = all_imgs
        self.indexes = np.arange(len(self.all_imgs))
        self.img_length_calc_function = img_length_calc_function
        self.batch_size = batch_size  # batch size
        self.shuffle = shuffle  # shuffle bool
        self.augment = augment  # augment data bool
        self.on_epoch_end()

    def __len__(self):
        """Denotes the smallest number of batches per epoch to include all images in the train set at least once"""
        return int(math.ceil(len(self.all_imgs) / self.batch_size))

    def on_epoch_end(self):
        """Updates indexes after each epoch"""
        self.indexes = np.arange(len(self.all_imgs))
        if self.shuffle:
            np.random.shuffle(self.indexes)

    def __getitem__(self, index):
        """Generate one batch of data"""
        # selects indices of data for next batch
        indexes = self.indexes[index * self.batch_size: (index + 1) * self.batch_size]
        # select data and load images
        x_imgs = []
        y_rpn_cls_targets = []
        y_rpn_regr_targets = []
        class_weights = []
        for index in indexes:
            height, width, resized_height, resized_width, img_data_aug, x_img = augment_and_resize_image(self.all_imgs[index], augment=self.augment)
            try:
                y_rpn_cls, y_rpn_regr = calc_rpn(img_data_aug, width, height, resized_width, resized_height, self.img_length_calc_function)
            except Exception as e:
                print("Error in generator: " + str(e))
                continue
            x_img, y_rpn_cls, y_rpn_regr = arrange_dims(x_img, y_rpn_cls, y_rpn_regr)
            x_imgs.append(x_img)
            y_rpn_cls_targets.append(y_rpn_cls)
            y_rpn_regr_targets.append(y_rpn_regr)
            class_weights.append([None, None])
        # class weights is currently an array of None to prevent TensorFlow 2.1 to provide the following warning:
        # WARNING:tensorflow:sample_weight modes were coerced from
        #    ...
        #    to
        #    ['...']
        x_imgs = np.array(x_imgs)
        x_imgs = np.reshape(x_imgs, (x_imgs.shape[0],) + x_imgs.shape[2:])
        y_rpn_cls_targets = np.array(y_rpn_cls_targets)
        y_rpn_regr_targets = np.array(y_rpn_regr_targets)
        y_rpn_cls_targets = np.reshape(y_rpn_cls_targets, (y_rpn_cls_targets.shape[0],) + y_rpn_cls_targets.shape[2:])
        y_rpn_regr_targets = np.reshape(y_rpn_regr_targets, (y_rpn_regr_targets.shape[0],) + y_rpn_regr_targets.shape[2:])
        return x_imgs, [y_rpn_cls_targets, y_rpn_regr_targets]


def augment_and_resize_image(img_data, augment=True):
    img_data_aug, x_img = data_augment.augment(img_data, augment=augment)
    (width, height) = (img_data_aug['width'], img_data_aug['height'])
    (rows, cols, _) = x_img.shape
    assert cols == width
    assert rows == height
    # get image dimensions for resizing
    (resized_width, resized_height) = get_new_img_size(width, height, detection_config.img_size)
    # resize the image so that smallest side has length = 640px
    x_img = cv2.resize(x_img, (resized_width, resized_height), interpolation=cv2.INTER_CUBIC)
    return height, width, resized_height, resized_width, img_data_aug, x_img


def arrange_dims(x_img, y_rpn_cls, y_rpn_regr):
    x_img = x_img[:, :, (2, 1, 0)]  # BGR -> RGB
    x_img = x_img.astype(np.float32)
    x_img = np.transpose(x_img, (2, 0, 1))
    x_img = np.expand_dims(x_img, axis=0)
    y_rpn_regr[:, y_rpn_regr.shape[1] // 2:, :, :] *= detection_config.std_scaling
    x_img = np.transpose(x_img, (0, 2, 3, 1))
    y_rpn_cls = np.transpose(y_rpn_cls, (0, 2, 3, 1))
    y_rpn_regr = np.transpose(y_rpn_regr, (0, 2, 3, 1))
    return x_img, y_rpn_cls, y_rpn_regr
