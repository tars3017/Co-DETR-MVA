import cv2
import mmcv
import argparse
import os, sys
import os.path as osp
import time
import cv2
import torch
import numpy as np
from PIL import Image, ImageDraw
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from loguru import logger
from typing import Any, List, Optional

from mmdet.apis import init_detector, inference_detector

co_detr_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(co_detr_path, 'Co-DETR'))
sys.path.append(os.path.join(co_detr_path, 'Co-DETR', 'boxmot'))
sys.path.append(os.path.join(co_detr_path, 'Co-DETR', 'sahi'))
print(f"path = {co_detr_path}")
from boxmot.trackers.botsort.botsort import BotSort
from boxmot.trackers.boosttrack.boosttrack import BoostTrack
from tracking.timer import Timer

from sahi.predict import get_sliced_prediction
from sahi.utils.compatibility import fix_full_shape_list, fix_shift_amount_list
from sahi.prediction import ObjectPrediction

IMAGE_EXT = [".jpg", ".jpeg", ".webp", ".bmp", ".png"]


# config_file = 'cropped_inference/co_dino_5scale_swin_large_3x_coco.py'
config_file = 'cropped_inference/co_dino_5scale_vit_large_coco.py'
# checkpoint_file = 'cropped/epoch_1.pth'
# checkpoint_file = 'cropped3/epoch_2.pth'
checkpoint_file = 'vit/epoch_1.pth'




# img = '../MVA2025_elsaA/OC_SORT/datasets/cropped_images/train/00001_260_0_0_640_640.jpg'  # or img = mmcv.imread(img), which will only load it once
# img = '00001.jpg'
# result = inference_detector(model, img)

# print(f"result {len(result)} {result[0].shape}")


def get_video_image_dict(root_path):
    video_image_dict = {}
    
    for video_name in os.listdir(root_path):
        video_path = osp.join(root_path, video_name)
        
        if not osp.isdir(video_path):
            continue

        image_paths = []
        for maindir, _, file_name_list in os.walk(video_path):
            for filename in file_name_list:
                ext = osp.splitext(filename)[1].lower()
                if ext in IMAGE_EXT:
                    image_paths.append(osp.join(maindir, filename))

        video_image_dict[video_name] = sorted(image_paths)

    return video_image_dict


class Predictor(object):
    def __init__(
        self,
        model,
        device,
        confthre,
    ):
        self.model = model
        self.device = device
        self.confthre = confthre

    def inference(self, img_path, timer):
        with torch.no_grad():
            timer.tic()

            prediction = get_sliced_prediction(
                img_path,
                self,
                slice_height=1200,
                slice_width=1200,
                overlap_height_ratio=0.1,
                overlap_width_ratio=0.1,
                verbose=True,
                auto_slice_resolution=True,
            )


        list_output = []
        for object_prediction in prediction.object_prediction_list:
            bbox = object_prediction.bbox
            score = object_prediction.score.value
            category_id = object_prediction.category.id

            list_output.append([bbox.minx, bbox.miny, bbox.maxx, bbox.maxy, score, category_id])
        list_output = np.array(list_output)
        # list_output = np.expand_dims(list_output, axis=0)
        # print(f"list_output shape {list_output.shape}")

        # print(f"conf thre {self.confthre}")
        file_name = img_path.split('/')[-1]
        # draw_top_boxes(img_path, list_output, output_path=f"./verify/output_{file_name}", conf_thresh=self.confthre)


        # list_output = torch.from_numpy(list_output).to(self.device)

        return list_output
        # return outputs, img_info


    def perform_inference(self, image: np.ndarray):
        """
        Prediction is performed using self.model and the prediction result is set to self._original_predictions.
        Args:
            image: np.ndarray
                A numpy array that contains the image to be predicted. 3 channel image should be in RGB order.
        """

        # Confirm model is loaded
        if self.model is None:
            raise ValueError("Model is not loaded, load it by calling .load_model()")


        # if image.shape[1:3] != (640, 640):
        #     self._original_predictions = torch.zeros((1, 0, 6)).to(self.device)
        #     self._original_shape = image.shape
        #     return

        # print(f"image shape {image.shape}")
        # convert (n, h, w, c) np image to n * (h, w, c) list
        # image = np.split(image, image.shape[0], axis=0)
        # print(f"image shape {list(image)}")
        # print(f"image shape {image.shape}")

        # for i in range(len(image)):
        #     image[i] = cv2.cvtColor(image[i], cv2.COLOR_RGB2BGR)
            # cv2.imwrite(f"verify/image_{i}.jpg", image[i])
        # height, width = image.shape[1:3]
        # convert np image to cv2 format
        # image, ratio = preproc(image, (height, width), self.rgb_means, self.std)
        # preproc_image = np.zeros((28, 3, 640, 640))
        # for i in range(len(image)):
            # preproc_image[i], ratio = preproc(image[i], (height, width), self.rgb_means, self.std)
            # preproc_image[i] = image[2].transpose(2, 0, 1)
            # cv2.imwrite(f"verify/image_{i}.jpg", preproc_image[i].transpose(1, 2, 0) * 144)
        # image = torch.from_numpy(image).unsqueeze(0).float().to(self.device)
        # image = torch.from_numpy(preproc_image).float().to(self.device)
        
        outputs = []
        with torch.no_grad():
            for i in range(len(image)):
                tmp = inference_detector(self.model, image[i])[0]
                tmp = np.hstack((tmp, np.ones((tmp.shape[0], 1), dtype=int)))
                tmp = np.pad(tmp, ((0, 1000 - tmp.shape[0]), (0, 0)), mode='constant', constant_values=0)
                outputs.append(tmp)
        
        outputs = torch.from_numpy(np.array(outputs)).to(self.device)

        

        self._original_predictions = outputs
        self._original_shape = image.shape

    def convert_original_predictions(
        self,
        shift_amount: Optional[List[List[int]]] = [[0, 0]],
        full_shape: Optional[List[List[int]]] = None,
    ):
        """
        Converts original predictions of the detection model to a list of
        prediction.ObjectPrediction object. Should be called after perform_inference().
        Args:
            shift_amount: list
                To shift the box and mask predictions from sliced image to full sized image, should be in the form of [shift_x, shift_y]
            full_shape: list
                Size of the full image after shifting, should be in the form of [height, width]
        """
        self._create_object_prediction_list_from_original_predictions(
            shift_amount_list=shift_amount,
            full_shape_list=full_shape,
        )
        # if self.category_remapping:
        #     self._apply_category_remapping()

    def _create_object_prediction_list_from_original_predictions(
        self,
        shift_amount_list: Optional[List[List[int]]] = [[0, 0]],
        full_shape_list: Optional[List[List[int]]] = None,
    ):
        """
        self._original_predictions is converted to a list of prediction.ObjectPrediction and set to
        self._object_prediction_list_per_image.
        Args:
            shift_amount_list: list of list
                To shift the box and mask predictions from sliced image to full sized image, should
                be in the form of List[[shift_x, shift_y],[shift_x, shift_y],...]
            full_shape_list: list of list
                Size of the full image after shifting, should be in the form of
                List[[height, width],[height, width],...]
        """
        original_predictions = self._original_predictions

        # compatibility for sahi v0.8.15
        shift_amount_list = fix_shift_amount_list(shift_amount_list)
        full_shape_list = fix_full_shape_list(full_shape_list)

        # handle all predictions
        object_prediction_list_per_image = []

        object_prediction_list = []
        for image_ind, image_predictions in enumerate(original_predictions):
            if image_ind >= len(shift_amount_list):
                break
            shift_amount = shift_amount_list[image_ind]
            # full_shape = None if full_shape_list is None else full_shape_list[image_ind]
            full_shape = full_shape_list[0]

            # Extract boxes and optional masks/obb
            boxes = image_predictions.data.cpu().detach().numpy()
            masks_or_points = None

            # Process each prediction
            for pred_ind, prediction in enumerate(boxes):
                # Get bbox coordinates
                bbox = prediction[:4].tolist()
                score = prediction[4]
                category_id = int(prediction[5])
                category_name = 'bird'

                # Fix box coordinates
                bbox = [max(0, coord) for coord in bbox]
                if full_shape is not None:
                    bbox[0] = min(full_shape[1], bbox[0])
                    bbox[1] = min(full_shape[0], bbox[1])
                    bbox[2] = min(full_shape[1], bbox[2])
                    bbox[3] = min(full_shape[0], bbox[3])

                if score < self.confthre:
                    continue

                # Ignore invalid predictions
                if not (bbox[0] < bbox[2]) or not (bbox[1] < bbox[3]):
                    # logger.warning(f"ignoring invalid prediction with bbox: {bbox}")
                    continue

                # Get segmentation or OBB points
                segmentation = None
                if masks_or_points is not None:
                    if self.has_mask:
                        bool_mask = masks_or_points[pred_ind]
                        # Resize mask to original image size
                        bool_mask = cv2.resize(
                            bool_mask.astype(np.uint8), (self._original_shape[1], self._original_shape[0])
                        )
                        segmentation = get_coco_segmentation_from_bool_mask(bool_mask)
                    else:  # is_obb
                        obb_points = masks_or_points[pred_ind]  # Get OBB points for this prediction
                        segmentation = [obb_points.reshape(-1).tolist()]

                    if len(segmentation) == 0:
                        continue

                # Create and append object prediction
                object_prediction = ObjectPrediction(
                    bbox=bbox,
                    category_id=category_id,
                    score=score,
                    segmentation=segmentation,
                    category_name=category_name,
                    shift_amount=shift_amount,
                    full_shape=self._original_shape[:2] if full_shape is None else full_shape,  # (height, width)
                )
                object_prediction_list.append(object_prediction)

            object_prediction_list_per_image.append(object_prediction_list)

        self._object_prediction_list_per_image = object_prediction_list_per_image

    @property
    def object_prediction_list(self) -> List[List[ObjectPrediction]]:
        if self._object_prediction_list_per_image is None:
            return []
        if len(self._object_prediction_list_per_image) == 0:
            return []
        return self._object_prediction_list_per_image[0]

    @property
    def object_prediction_list_per_image(self) -> List[List[ObjectPrediction]]:
        return self._object_prediction_list_per_image or []

    @property
    def original_predictions(self):
        return self._original_predictions


def draw_top_boxes(image_path, prediction, output_path="output_with_boxes.jpg", conf_thresh=0.2):
    """
    Draw the predicted boxes whose confidence is above conf_thresh.
    
    Args:
        image_path (str): Path to the input image.
        prediction (torch.Tensor): [1, num_queries, 6] tensor with [x_center, y_center, w, h, score, 1].
        orig_size (torch.Tensor): Original image size [h, w].
        target_size (torch.Tensor): Resized image size [new_h, new_w].
        output_path (str): Path to save the output image.
        conf_thresh (float): Confidence threshold.
    """
    # Load the image with OpenCV (BGR) and convert to RGB & PIL for drawing
    img = cv2.imread(image_path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(img)
    
    # Extract predictions
    # print(f"prediction shape {prediction.shape}")
    if prediction.shape[0] == 0:
        return
    pred = prediction  # [num_queries, 6]
    boxes = pred[:, :4]   # [num_queries, 4] with format: [x_center, y_center, w, h]
    scores = pred[:, 4]   # [num_queries]
    
    # Filter boxes by confidence threshold
    keep = scores >= conf_thresh
    filtered_boxes = boxes[keep]
    filtered_scores = scores[keep]
    
    # Convert from [x_center, y_center, w, h] to [x1, y1, x2, y2]
    # boxes_xyxy = torch.zeros_like(filtered_boxes)
    # boxes_xyxy[:, 0] = filtered_boxes[:, 0] - filtered_boxes[:, 2] / 2  # x1
    # boxes_xyxy[:, 1] = filtered_boxes[:, 1] - filtered_boxes[:, 3] / 2  # y1
    # boxes_xyxy[:, 2] = filtered_boxes[:, 0] + filtered_boxes[:, 2] / 2  # x2
    # boxes_xyxy[:, 3] = filtered_boxes[:, 1] + filtered_boxes[:, 3] / 2  # y2
    
    orig_h, orig_w = img.shape[:2]  # original sizes
    
    # Draw each box on the image
    draw = ImageDraw.Draw(img_pil)
    for box, score in zip(filtered_boxes, filtered_scores):
        x1, y1, x2, y2 = box.tolist()
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(orig_w, x2), min(orig_h, y2)
        if x2 > x1 and y2 > y1:
            draw.rectangle([x1, y1, x2, y2], outline="red", width=2)
            draw.text((x1, y1 - 10), f"{score:.2f}", fill="red")
            print(f"Draw box at {x1:.2f}, {y1:.2f}, {x2:.2f}, {y2:.2f} with score {score:.2f}")
    
    img_pil.save(output_path)
    print(f"Saved image with boxes to {output_path}")


# draw_top_boxes(img, result, output_path="output_with_boxes.jpg", conf_thresh=0.2)

def predict_videos(num_workers=20):
    res_folder = 'tracking_vit'
    if not os.path.exists(res_folder):
        os.makedirs(res_folder)
    if not os.path.exists('verify'):
        os.makedirs('verify')
    model = init_detector(config_file, checkpoint_file, device='cuda:0')
    predictor = Predictor(model, device=0, confthre=0.1)
    video_image_dict = get_video_image_dict('../DQ-DETR/data/pub_test')

    # def process_video(video_name, files):
    for video_name, files in dict(reversed(list(video_image_dict.items()))).items():
    # for video_name, files in video_image_dict.items():
        # tracker = BotSort(
        #     reid_weights=Path("osnet_x0_25_msmt17.pt"),
        #     device=0,
        #     half=False,
        #     proximity_thresh=0.1,
        #     with_reid=False,
        #     match_thresh=0.1,
        #     new_track_thresh=0.1,
        #     track_low_thresh=0.1,
        #     track_high_thresh=0.2,
        #     appearance_thresh=0.1,
        # )
        tracker = BoostTrack(
            reid_weights=Path("osnet_x0_25_msmt17.pt"),
            device=0,
            half=False,
            det_thresh=0.5,
            iou_threshold=0.1,
            min_box_area=0,
            aspect_ratio_thresh=10,

            # haven't tried yet
            # use_rich_s=True,
            # use_sb=True,
            # use_vt=True,
        )
    
        timer = Timer()
        results = []
        for frame_id, img_path in enumerate(files, 1):
            # outputs, img_info = predictor.inference(img_path, timer)
            img = cv2.imread(img_path)
            # outputs = inference_detector(model, img_path) 
            outputs = predictor.inference(img_path, timer)
            # draw_top_boxes(img_path, outputs, output_path=f"verify/img_{frame_id}.jpg", conf_thresh=0.1)
            if outputs is not None and outputs.shape[0] > 0:
                # print(f"outputs {outputs}")
               
                # online_targets = tracker.update(outputs[0], [img_info['height'], img_info['width']], img.shape[:2])
                online_targets = tracker.update(
                    # np.hstack((outputs[0], np.ones((outputs[0].shape[0], 1), dtype=np.int))),
                    outputs,
                    cv2.imread(img_path),
                )
                online_tlwhs = []
                online_ids = []
                tids = []
                for t in online_targets:
                    tlwh = [t[0], t[1], t[2] - t[0], t[3] - t[1]]
                    tid = t[4]
                    vertical = tlwh[2] / tlwh[3] > 4
                    if tid in tids:
                        logger.warning(f"Duplicate ID {tid} detected in frame {frame_id} of video {video_name}.")
                        continue
                    if tlwh[2] * tlwh[3] > 0 and not vertical:
                        online_tlwhs.append(tlwh)
                        online_ids.append(tid)
                        tids.append(tid)
                        results.append(
                            f"{frame_id},{tid},{tlwh[0]:.2f},{tlwh[1]:.2f},{tlwh[2]:.2f},{tlwh[3]:.2f},1,1,1\n"
                        )
                        print(f"{video_name} {frame_id} {tid} ({tlwh[0]:.2f} {tlwh[1]:.2f} {tlwh[2]:.2f} {tlwh[3]:.2f})")
                timer.toc()
            else:
                timer.toc()

            if frame_id % 20 == 0:
                logger.info('Processing frame {} ({:.2f} fps)'.format(frame_id, 1. / max(1e-5, timer.average_time)))

        # if args.save_result:
        res_file = osp.join(res_folder, f"{video_name}.txt")
        with open(res_file, 'w') as f:
            f.writelines(results)
        logger.info(f"save results to {res_file}")

    # Use ThreadPoolExecutor to process videos in parallel
    # with ThreadPoolExecutor(max_workers=num_workers) as executor:
    #     futures = [
    #         executor.submit(process_video, video_name, files)
    #         for video_name, files in video_image_dict.items()
    #     ]
    #     for future in futures:
    #         future.result()  # Wait for all threads to complete


if __name__ == '__main__':
    predict_videos()