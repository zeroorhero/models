#
# -*- coding: utf-8 -*-
#
# Copyright (c) 2019 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

#

import time
from argparse import ArgumentParser

import tensorflow as tf
from tensorflow.python.tools.optimize_for_inference_lib import optimize_for_inference
from tensorflow.python.framework import dtypes
from tensorflow.core.protobuf import rewriter_config_pb2

import datasets
import numpy as np

INPUTS = 'input_tensor'
OUTPUTS = 'softmax_tensor'

RESNET_IMAGE_SIZE = 224


class eval_classifier_optimized_graph:
  """Evaluate image classifier with optimized TensorFlow graph"""

  def __init__(self):

    arg_parser = ArgumentParser(description='Parse args')

    arg_parser.add_argument('-b', "--batch-size",
                            help="Specify the batch size. If this " \
                                 "parameter is not specified or is -1, the " \
                                 "largest ideal batch size for the model will " \
                                 "be used.",
                            dest="batch_size", type=int, default=-1)

    arg_parser.add_argument('-e', "--num-inter-threads",
                            help='The number of inter-thread.',
                            dest='num_inter_threads', type=int, default=0)

    arg_parser.add_argument('-a', "--num-intra-threads",
                            help='The number of intra-thread.',
                            dest='num_intra_threads', type=int, default=0)

    arg_parser.add_argument('-m', "--model-name",
                            help='Specify the model name to run benchmark for',
                            dest='model_name')

    arg_parser.add_argument('-g', "--input-graph",
                            help='Specify the input graph for the transform tool',
                            dest='input_graph')

    arg_parser.add_argument('-d', "--data-location",
                            help='Specify the location of the data. '
                                 'If this parameter is not specified, '
                                 'the benchmark will use random/dummy data.',
                            dest="data_location", default=None)

    arg_parser.add_argument('-r', "--accuracy-only",
                            help='For accuracy measurement only.',
                            dest='accuracy_only', action='store_true')
    arg_parser.add_argument('--calibrate', dest='calibrate',
                            help='Run accuracy with calibration data,'
                                 'to generate min_max ranges, calibrate=[True/False]',
                            type=bool, default=False)
    arg_parser.add_argument("--results-file-path",
                            help="File path for the inference results",
                            dest="results_file_path", default=None)
    arg_parser.add_argument("--warmup-steps", type=int, default=10,
                            help="number of warmup steps")
    arg_parser.add_argument("--steps", type=int, default=50,
                            help="number of steps")

    arg_parser.add_argument(
      '--data-num-inter-threads', dest='data_num_inter_threads',
      help='number threads across operators',
      type=int, default=32)
    arg_parser.add_argument(
      '--data-num-intra-threads', dest='data_num_intra_threads',
      help='number threads for data layer operator',
      type=int, default=14)
    arg_parser.add_argument(
      '--num-cores', dest='num_cores',
      help='number of cores',
      type=int, default=28)
    arg_parser.add_argument(
      '--data-type', dest='data_type',
      choices=['float32', 'fp16', 'bfloat16'],
      help='data type used for computation',
      default="float32")

    self.args = arg_parser.parse_args()
    # validate the arguements
    self.validate_args()

  def write_results_output(self, predictions, filenames, labels):
    # If a results_file_path is provided, write the predictions to the file
    if self.args.results_file_path:
      top_predictions = np.argmax(predictions, 1)
      with open(self.args.results_file_path, "a") as fp:
        for filename, expected_label, top_prediction in zip(filenames, labels, top_predictions):
          fp.write("{},{},{}\n".format(filename, expected_label, top_prediction))

  def run(self):
    """run benchmark with optimized graph"""

    dtype = self.args.data_type
    print("*** Run inference using data type:", dtype, "***")

    data_config = tf.compat.v1.ConfigProto()
    data_config.intra_op_parallelism_threads = self.args.data_num_intra_threads
    data_config.inter_op_parallelism_threads = self.args.data_num_inter_threads
    data_config.use_per_session_threads = 1

    infer_config = tf.compat.v1.ConfigProto()
    infer_config.intra_op_parallelism_threads = self.args.num_intra_threads
    infer_config.inter_op_parallelism_threads = self.args.num_inter_threads
    infer_config.use_per_session_threads = 1
    infer_config.graph_options.rewrite_options.remapping = (
                  rewriter_config_pb2.RewriterConfig.AGGRESSIVE)
    if dtype == 'fp16':
      infer_config.graph_options.rewrite_options.auto_mixed_precision = (
                    rewriter_config_pb2.RewriterConfig.ON)


    data_graph = tf.Graph()
    with data_graph.as_default():
      if (self.args.data_location):
        print("Inference with real data.")
        if self.args.calibrate:
            subset = 'calibration'
        else:
            subset = 'validation'
        dataset = datasets.ImagenetData(self.args.data_location)
        preprocessor = dataset.get_image_preprocessor()(
            RESNET_IMAGE_SIZE, RESNET_IMAGE_SIZE, self.args.batch_size,
            num_cores=self.args.num_cores,
            resize_method='crop')

        images, labels, filenames = preprocessor.minibatch(dataset, subset=subset)

        # If a results file path is provided, then start the prediction output file
        if self.args.results_file_path:
          with open(self.args.results_file_path, "w+") as fp:
            fp.write("filename,actual,prediction\n")
      else:
        print("Inference with dummy data.")
        input_shape = [self.args.batch_size, RESNET_IMAGE_SIZE, RESNET_IMAGE_SIZE, 3]
        images = tf.random.uniform(input_shape, 0.0, 255.0, dtype=tf.float32, name='synthetic_images')

    infer_graph = tf.Graph()
    with infer_graph.as_default():
      graph_def = tf.compat.v1.GraphDef()
      with tf.compat.v1.gfile.FastGFile(self.args.input_graph, 'rb') as input_file:
        input_graph_content = input_file.read()
        graph_def.ParseFromString(input_graph_content)

      output_graph = optimize_for_inference(graph_def, [INPUTS],
                              [OUTPUTS], dtypes.float32.as_datatype_enum, False)
      tf.import_graph_def(output_graph, name='')

    # Definite input and output Tensors for detection_graph
    input_tensor = infer_graph.get_tensor_by_name(INPUTS + ':0')
    output_tensor = infer_graph.get_tensor_by_name(OUTPUTS + ':0')

    data_sess  = tf.compat.v1.Session(graph=data_graph,  config=data_config)
    infer_sess = tf.compat.v1.Session(graph=infer_graph, config=infer_config)

    num_processed_images = 0
    num_remaining_images = dataset.num_examples_per_epoch(subset=subset) - num_processed_images \
        if self.args.data_location else (self.args.steps * self.args.batch_size)

    if (not self.args.accuracy_only):
      iteration = 0
      warm_up_iteration = self.args.warmup_steps
      total_run = self.args.steps
      total_time = 0

      while num_remaining_images >= self.args.batch_size and iteration < total_run:
        iteration += 1
        tf_filenames = None
        np_labels = None
        data_load_start = time.time()
        if self.args.results_file_path:
          image_np, np_labels, tf_filenames = data_sess.run([images, labels, filenames])
        else:
          image_np = data_sess.run(images)

        data_load_time = time.time() - data_load_start

        num_processed_images += self.args.batch_size
        num_remaining_images -= self.args.batch_size

        start_time = time.time()
        predictions = infer_sess.run(output_tensor, feed_dict={input_tensor: image_np})
        time_consume = time.time() - start_time

        # Write out the file name, expected label, and top prediction
        self.write_results_output(predictions, tf_filenames, np_labels)

        # only add data loading time for real data, not for dummy data
        if self.args.data_location:
          time_consume += data_load_time

        print('Iteration %d: %.6f sec' % (iteration, time_consume))
        if iteration > warm_up_iteration:
          total_time += time_consume

      time_average = total_time / (iteration - warm_up_iteration)
      print('Average time: %.6f sec' % (time_average))

      print('Batch size = %d' % self.args.batch_size)
      if (self.args.batch_size == 1):
        print('Latency: %.3f ms' % (time_average * 1000))
      # print throughput for both batch size 1 and 128
      print('Throughput: %.3f images/sec' % (self.args.batch_size / time_average))

    else: # accuracy check
      total_accuracy1, total_accuracy5 = (0.0, 0.0)

      while num_remaining_images >= self.args.batch_size:
        # Reads and preprocess data
        tf_filenames = None
        if self.args.results_file_path:
          np_images, np_labels, tf_filenames = data_sess.run([images, labels, filenames])
        else:
          np_images, np_labels = data_sess.run([images, labels])
        num_processed_images += self.args.batch_size
        num_remaining_images -= self.args.batch_size

        start_time = time.time()
        # Compute inference on the preprocessed data
        predictions = infer_sess.run(output_tensor,
                               {input_tensor: np_images})
        elapsed_time = time.time() - start_time

        # Write out the file name, expected label, and top prediction
        self.write_results_output(predictions, tf_filenames, np_labels)

        with tf.Graph().as_default() as accu_graph:
          accuracy1 = tf.reduce_sum(
            input_tensor=tf.cast(tf.nn.in_top_k(predictions=tf.constant(predictions),
                                   targets=tf.constant(np_labels), k=1), tf.float32))

          accuracy5 = tf.reduce_sum(
            input_tensor=tf.cast(tf.nn.in_top_k(predictions=tf.constant(predictions),
                                   targets=tf.constant(np_labels), k=5), tf.float32))
          with tf.compat.v1.Session(config=infer_config) as accu_sess:
            np_accuracy1, np_accuracy5 = accu_sess.run([accuracy1, accuracy5])

          total_accuracy1 += np_accuracy1
          total_accuracy5 += np_accuracy5

        print("Iteration time: %0.4f ms" % elapsed_time)
        print("Processed %d images. (Top1 accuracy, Top5 accuracy) = (%0.4f, %0.4f)" \
                  % (num_processed_images, total_accuracy1 / num_processed_images,
                     total_accuracy5 / num_processed_images))

  def validate_args(self):
    """validate the arguments"""

    if not self.args.data_location:
      if self.args.accuracy_only:
        raise ValueError("You must use real data for accuracy measurement.")


if __name__ == "__main__":
  evaluate_opt_graph = eval_classifier_optimized_graph()
  evaluate_opt_graph.run()
