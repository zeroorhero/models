<!--- 0. Title -->
# RFCN inference

<!-- 10. Description -->

This document has instructions for running RFCN inference using
Intel-optimized TensorFlow.


<!--- 30. Datasets -->
## Dataset

The [COCO validation dataset](http://cocodataset.org) is used in these
RFCN quickstart scripts. The inference quickstart scripts use raw images,
and the accuracy quickstart scripts require the dataset to be converted
into the TF records format.
See the [COCO dataset](/datasets/coco/README.md) for instructions on
downloading and preprocessing the COCO validation dataset.


<!--- 40. Quick Start Scripts -->
## Quick Start Scripts

| Script name | Description |
|-------------|-------------|
| [`inference.sh`](/quickstart/object_detection/tensorflow/rfcn/inference/cpu/inference.sh) | Runs inference on a directory of raw images for 500 steps and outputs performance metrics. |
| [`accuracy.sh`](/quickstart/object_detection/tensorflow/rfcn/inference/cpu/accuracy.sh) | Processes the TF records to run inference and check accuracy on the results. |

<!-- 60. Docker -->
## Docker

When running in docker, the RFCN inference container includes the
libraries and the model package, which are needed to run RFCN inference. To run the quickstart scripts, you'll need to provide volume mounts for the
[COCO validation dataset](/dataset/coco/README.md) and an output directory
where log files will be written.

To run inference with performance metrics:
```
DATASET_DIR=<path to the coco val2017 raw image directory (ex: /home/user/coco_dataset/val2017)>
PRECISION=<set the precision to "int8" or "fp32">
OUTPUT_DIR=<directory where log files will be written>
# For a custom batch size, set env var `BATCH_SIZE` or it will run with a default value.
export BATCH_SIZE=<customized batch size value>

docker run \
  --env DATASET_DIR=${DATASET_DIR} \
  --env PRECISION=${PRECISION} \
  --env OUTPUT_DIR=${OUTPUT_DIR} \
  --env BATCH_SIZE=${BATCH_SIZE} \
  --env http_proxy=${http_proxy} \
  --env https_proxy=${https_proxy} \
  --volume ${DATASET_DIR}:${DATASET_DIR} \
  --volume ${OUTPUT_DIR}:${OUTPUT_DIR} \
  --privileged --init -t \
  intel/object-detection:tf-latest-rfcn-inference \
  /bin/bash quickstart/<script_name>.sh
```

When the run completes, the log tail will note the average duration per step:

```
Avg. Duration per Step: ...
Ran inference with batch size 1
Log file location: ${OUTPUT_DIR}/benchmark_rfcn_inference_fp32_20200620_002239.log
```

To get accuracy metrics:
```
DATASET_DIR=<path to TF record file (ex: /home/user/coco_output/coco_val.record)>
OUTPUT_DIR=<directory where log files will be written>

docker run \
  --env DATASET_DIR=${DATASET_DIR} \
  --env OUTPUT_DIR=${OUTPUT_DIR} \
  --env http_proxy=${http_proxy} \
  --env https_proxy=${https_proxy} \
  --volume ${DATASET_DIR}:${DATASET_DIR} \
  --volume ${OUTPUT_DIR}:${OUTPUT_DIR} \
  --privileged --init -t \
  intel/object-detection:tf-latest-rfcn-inference \
  /bin/bash quickstart/fp32_accuracy.sh
```

Below is a sample log file tail when running for accuracy:

```
Running per image evaluation...
Evaluate annotation type *bbox*
DONE (t=10.41s).
Accumulating evaluation results...
DONE (t=1.62s).
 Average Precision  (AP) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.347
 Average Precision  (AP) @[ IoU=0.50      | area=   all | maxDets=100 ] = 0.532
 Average Precision  (AP) @[ IoU=0.75      | area=   all | maxDets=100 ] = 0.389
 Average Precision  (AP) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.347
 Average Precision  (AP) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = -1.000
 Average Precision  (AP) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = -1.000
 Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=  1 ] = 0.282
 Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets= 10 ] = 0.396
 Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.400
 Average Recall     (AR) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.400
 Average Recall     (AR) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = -1.000
 Average Recall     (AR) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = -1.000
Ran inference with batch size 1
Log file location: ${OUTPUT_DIR}/benchmark_rfcn_inference_fp32_20200620_002841.log
```

If you are new to docker and are running into issues with the container,
see [this document](https://github.com/IntelAI/models/tree/master/docs/general/docker.md)
for troubleshooting tips.

<!--- 80. License -->
## License

[LICENSE](/LICENSE)

