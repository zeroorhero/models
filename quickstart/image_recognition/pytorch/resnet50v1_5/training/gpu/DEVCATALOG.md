# PyTorch ResNet50_v1.5 Training

## Description 
This document has instructions for running ResNet50 v1.5 training with BFloat16 precision on Intel® Data Center GPU Max Series using Intel® Extension for PyTorch.

## Datasets
Download and extract the ImageNet2012 training and validation dataset from [http://www.image-net.org/ (http://www.image-net.org/),then move validation images to labeled subfolders, using
[the valprep.sh shell script](https://raw.githubusercontent.com/soumith/imagenetloader.torch/master/valprep.sh)

After running the data prep script and extracting the images, your folder structure
should look something like this:
```
imagenet
├── train
│   ├── n02085620
│   │   ├── n02085620_10074.JPEG
│   │   ├── n02085620_10131.JPEG
│   │   ├── n02085620_10621.JPEG
│   │   └── ...
│   └── ...
└── val
    ├── n01440764
    │   ├── ILSVRC2012_val_00000293.JPEG
    │   ├── ILSVRC2012_val_00002138.JPEG
    │   ├── ILSVRC2012_val_00003014.JPEG
    │   └── ...
    └── ...
```
The folder that contains the `val` and `train` directories should be set as the
`DATASET_DIR` environment variable before running the quickstart scripts.

## Quick Start Scripts
| Script name | Description |
|-------------|-------------|
| `training_plain_format.sh` | Runs ResNet50 v1.5 BF16 training (plain format) on two tiles |
| `ddp_training_plain_format_nchw.sh` | Runs ResNet50 v1.5 Distributed Data Parallel BF16 training on two tiles |

Requirements:
* Host machine has Intel(R) Data Center Max Series GPU
* Follow instructions to install GPU-compatible driver [540](https://dgpu-docs.intel.com/releases/stable_540_20221205.html#ubuntu-22-04)
* Docker

### Docker pull command:
```
docker pull intel/image-recognition:pytorch-max-gpu-resnet50v1-5-training
```
The ResNet50 v1.5 training container includes scripts,model and libraries need to run BF16 training. To run the `ddp_training_plain_format_nchw.sh` quickstart script using this container, you'll need to provide volume mounts for the ImageNet dataset. You will need to provide an output directory where log files will be written. 

```
export DATASET_DIR=${PWD}/imagenet
export OUTPUT_DIR=${PWD}/logs

DOCKER_ARGS="--rm --init -it"
IMAGE_NAME=intel/image-recognition:pytorch-max-gpu-resnet50v1-5-training

export SCRIPT=quickstart/ddp_training_plain_format_nchw.sh
export Tile=2

VIDEO=$(getent group video | sed -E 's,^video:[^:]*:([^:]*):.*$,\1,')
RENDER=$(getent group render | sed -E 's,^render:[^:]*:([^:]*):.*$,\1,')
test -z "$RENDER" || RENDER_GROUP="--group-add ${RENDER}"

docker run \
  --group-add ${VIDEO} \
  ${RENDER_GROUP} \
  --device=/dev/dri \
  --shm-size=10G \
  --privileged \
  --ipc=host \
  --env DATASET_DIR=${DATASET_DIR} \
  --env OUTPUT_DIR=${OUTPUT_DIR} \
  --env Tile=${Tile} \
  --env http_proxy=${http_proxy} \
  --env https_proxy=${https_proxy} \
  --env no_proxy=${no_proxy} \
  --volume ${DATASET_DIR}:${DATASET_DIR} \
  --volume ${OUTPUT_DIR}:${OUTPUT_DIR} \
  --volume /dev/dri:/dev/dri \
  ${DOCKER_ARGS} \
  $IMAGE_NAME \
  /bin/bash $SCRIPT
  ```

