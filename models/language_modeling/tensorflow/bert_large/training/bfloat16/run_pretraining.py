# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Run masked LM/next sentence masked_lm pre-training for BERT."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import modeling
import optimization
import tensorflow as tf
import generic_ops as bf
import math

import sys
from tensorflow.core.protobuf import config_pb2
from tensorflow.python.training.session_run_hook import SessionRunArgs
from tensorflow.python.training import training_util
from tensorflow.python.platform import gfile
from tensorflow.python.client import timeline
from datetime import datetime

class LoggerHook(tf.estimator.SessionRunHook):
  """ Logs runtime. """
  def __init__(self, batch_size, run_profile):
    self.batch_size = batch_size
    self.run_profile = run_profile

  def begin(self):
    self._step = 0
    self._total_duration = 0
    self._warmup = 2
    self._global_step_tensor = training_util._get_or_create_global_step_read()

  def before_run(self, run_context):
    self._start_time = datetime.now()
    opts = config_pb2.RunOptions(trace_level=config_pb2.RunOptions.FULL_TRACE)
    requests = {"global_step": self._global_step_tensor}
    if self.run_profile:
      return SessionRunArgs(requests, options=opts)
    else:
      return SessionRunArgs(requests)

  def after_run(self, run_context, run_values):
    self._step += 1
    duration = datetime.now() - self._start_time
    ms = duration.total_seconds() * 1000.00
    if self._step > self._warmup:
      self._total_duration += ms
      if self._step % 1 == 0:
        print("Current step: %d, time in ms: %.2f" %(self._step, ms))
    else:
      print("Warmup step: %d, time in ms: %.2f" %(self._step, ms))
    sys.stdout.flush()
    if self._step == 4 and self.run_profile:
      with gfile.Open('timeline-bert.json', "w") as f:
        trace = timeline.Timeline(run_values.run_metadata.step_stats)
        f.write(trace.generate_chrome_trace_format())

  def end(self, run_context):
    print("self._step: %d" %self._step)
    print("Total time spent (after warmup): %.2f ms" %(self._total_duration))
    print("Time spent per iteration (after warmup): %.2f ms" %(self._total_duration/(self._step - self._warmup)))
    time_takes = self._total_duration / (self._step - self._warmup)
    if self.batch_size == 1:
      print("Latency is %.3f ms" % (time_takes))
    print("Throughput is %.3f samples/sec" % (self.batch_size * 1000 / time_takes))
    sys.stdout.flush()

global is_mpi
try:
  import horovod.tensorflow as hvd
  hvd.init()
  is_mpi = hvd.size()
except ImportError:
  is_mpi = 0
  print("No MPI horovod support, this is running in no-MPI mode!")

#flags = tf.flags
from absl import app
#from absl import flags
from absl import logging
flags = tf.compat.v1.flags


FLAGS = flags.FLAGS

## Required parameters
flags.DEFINE_string(
    "bert_config_file", None,
    "The config json file corresponding to the pre-trained BERT model. "
    "This specifies the model architecture.")

flags.DEFINE_string(
    "input_file", None,
    "Input TF example files (can be a glob or comma separated).")

flags.DEFINE_string(
    "output_dir", None,
    "The output directory where the model checkpoints will be written.")

## Other parameters
flags.DEFINE_string(
    "init_checkpoint", None,
    "Initial checkpoint (usually from a pre-trained BERT model).")

flags.DEFINE_integer(
    "max_seq_length", 128,
    "The maximum total input sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated, and sequences shorter "
    "than this will be padded. Must match data generation.")

flags.DEFINE_integer(
    "max_predictions_per_seq", 20,
    "Maximum number of masked LM predictions per sequence. "
    "Must match data generation.")

flags.DEFINE_bool("do_train", False, "Whether to run training.")

flags.DEFINE_bool("do_eval", False, "Whether to run eval on the dev set.")

flags.DEFINE_integer("train_batch_size", 32, "Total batch size for training.")

flags.DEFINE_integer("accum_steps", 1, "Accumulation steps for batch size greater than 32.")

flags.DEFINE_integer("eval_batch_size", 8, "Total batch size for eval.")

flags.DEFINE_float("learning_rate", 5e-5, "The initial learning rate for Adam.")

flags.DEFINE_integer("num_train_steps", 100000, "Number of training steps.")

flags.DEFINE_integer("num_warmup_steps", 10000, "Number of warmup steps.")

flags.DEFINE_integer("save_checkpoints_steps", 1000,
                     "How often to save the model checkpoint.")

flags.DEFINE_integer("iterations_per_loop", 1000,
                     "How many steps to make in each estimator call.")

flags.DEFINE_integer("max_eval_steps", 100, "Maximum number of eval steps.")

flags.DEFINE_integer("inter_op_parallelism_threads", 2, "inter_op_parallelism_threads.")

flags.DEFINE_integer("intra_op_parallelism_threads", 20, "intra_op_parallelism_threads.")

flags.DEFINE_bool("use_tpu", False, "Whether to use TPU or GPU/CPU.")

flags.DEFINE_string(
    "tpu_name", None,
    "The Cloud TPU to use for training. This should be either the name "
    "used when creating the Cloud TPU, or a grpc://ip.address.of.tpu:8470 "
    "url.")

flags.DEFINE_string(
    "tpu_zone", None,
    "[Optional] GCE zone where the Cloud TPU is located in. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

flags.DEFINE_string(
    "gcp_project", None,
    "[Optional] Project name for the Cloud TPU-enabled project. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

flags.DEFINE_string("master", None, "[Optional] TensorFlow master URL.")

flags.DEFINE_string("precision", "fp32", "[Optional] TensorFlow training precision.")

flags.DEFINE_bool("new_bf16_scope", True, "[Optional] To change scopes for bfloat16."
                                     " Set this to False to enable bfloat16 scope for optimizer")

flags.DEFINE_integer(
    "num_tpu_cores", 8,
    "Only used if `use_tpu` is True. Total number of TPU cores to use.")


flags.DEFINE_bool("profile", False, "[Optional] To enable Tensorflow profile hook."
                                    "The profile output will be generated in the output_dir")

flags.DEFINE_bool(
    "disable_v2_bevior", False, "If true, disable the new features in TF 2.x.")

flags.DEFINE_bool(
    "optimized_softmax", False,
    "[Optional] If true, use experimental bf16 softmax for internal softmaxes inside each layer."
    "           Be careful this flag will crash model with incompatible TF.")

flags.DEFINE_bool(
    "experimental_gelu", False,
    "[Optional] If true, use more experimental op(gelu) in model."
    "           Be careful this flag will crash model with incompatible TF.")


def model_fn_builder(bert_config, init_checkpoint, learning_rate,
                     num_train_steps, num_warmup_steps, accum_steps, use_tpu,
                     use_one_hot_embeddings, use_multi_cpu=is_mpi):
  """Returns `model_fn` closure for TPUEstimator."""

  def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
    """The `model_fn` for TPUEstimator."""

    tf.compat.v1.logging.info("*** Features ***")
    for name in sorted(features.keys()):
      tf.compat.v1.logging.info("  name = %s, shape = %s" % (name, features[name].shape))

    input_ids = features["input_ids"]
    input_mask = features["input_mask"]
    segment_ids = features["segment_ids"]
    masked_lm_positions = features["masked_lm_positions"]
    masked_lm_ids = features["masked_lm_ids"]
    masked_lm_weights = features["masked_lm_weights"]
    next_sentence_labels = features["next_sentence_labels"]

    is_training = (mode == tf.estimator.ModeKeys.TRAIN)


    if bert_config.precision == "bfloat16" and bert_config.new_bf16_scope == True:
      with tf.compat.v1.tpu.bfloat16_scope():
        bf.set_global_precision(tf.bfloat16)
        tf.compat.v1.logging.info("*** New bfloat16 scope set***")
        model = modeling.BertModel(
          config=bert_config,
          is_training=is_training,
          input_ids=input_ids,
          input_mask=input_mask,
          token_type_ids=segment_ids,
          use_one_hot_embeddings=use_one_hot_embeddings)
    else :
      model = modeling.BertModel(
        config=bert_config,
        is_training=is_training,
        input_ids=input_ids,
        input_mask=input_mask,
        token_type_ids=segment_ids,
        use_one_hot_embeddings=use_one_hot_embeddings)

    (masked_lm_loss,
     masked_lm_example_loss, masked_lm_log_probs) = get_masked_lm_output(
         bert_config, model.get_sequence_output(), model.get_embedding_table(),
         masked_lm_positions, masked_lm_ids, masked_lm_weights)

    (next_sentence_loss, next_sentence_example_loss,
     next_sentence_log_probs) = get_next_sentence_output(
         bert_config, model.get_pooled_output(), next_sentence_labels)

    total_loss = masked_lm_loss + next_sentence_loss

    tvars = tf.compat.v1.trainable_variables()

    initialized_variable_names = {}
    scaffold_fn = None
    if init_checkpoint:
      (assignment_map, initialized_variable_names
      ) = modeling.get_assignment_map_from_checkpoint(tvars, init_checkpoint)
      if use_tpu:

        def tpu_scaffold():
          tf.compat.v1.train.init_from_checkpoint(init_checkpoint, assignment_map)
          return tf.compat.v1.train.Scaffold()

        scaffold_fn = tpu_scaffold
      else:
        tf.compat.v1.train.init_from_checkpoint(init_checkpoint, assignment_map)

    tf.compat.v1.logging.info("**** Trainable Variables ****")
    for var in tvars:
      init_string = ""
      if var.name in initialized_variable_names:
        init_string = ", *INIT_FROM_CKPT*"
      tf.compat.v1.logging.info("  name = %s, shape = %s%s", var.name, var.shape,
                      init_string)

    output_spec = None
    if mode == tf.estimator.ModeKeys.TRAIN:
      train_op = optimization.create_optimizer(
              total_loss, learning_rate, num_train_steps, num_warmup_steps, 
                            accum_steps, use_tpu=use_tpu, use_multi_cpu=is_mpi)

      log_hook = bf.logTheLossHook(total_loss, FLAGS.accum_steps*3)
      output_spec = tf.compat.v1.estimator.tpu.TPUEstimatorSpec(
          mode=mode,
          loss=total_loss,
          train_op=train_op,
          training_hooks=[log_hook],
          scaffold_fn=scaffold_fn)
    elif mode == tf.estimator.ModeKeys.EVAL:

      def metric_fn(masked_lm_example_loss, masked_lm_log_probs, masked_lm_ids,
                    masked_lm_weights, next_sentence_example_loss,
                    next_sentence_log_probs, next_sentence_labels):
        """Computes the loss and accuracy of the model."""
        masked_lm_log_probs = tf.reshape(masked_lm_log_probs,
                                         [-1, masked_lm_log_probs.shape[-1]])
        masked_lm_predictions = tf.argmax(
            input=masked_lm_log_probs, axis=-1, output_type=tf.int32)
        masked_lm_example_loss = tf.reshape(masked_lm_example_loss, [-1])
        masked_lm_ids = tf.reshape(masked_lm_ids, [-1])
        masked_lm_weights = tf.reshape(masked_lm_weights, [-1])
        masked_lm_accuracy = tf.compat.v1.metrics.accuracy(
            labels=masked_lm_ids,
            predictions=masked_lm_predictions,
            weights=masked_lm_weights)
        masked_lm_mean_loss = tf.compat.v1.metrics.mean(
            values=masked_lm_example_loss, weights=masked_lm_weights)

        next_sentence_log_probs = tf.reshape(
            next_sentence_log_probs, [-1, next_sentence_log_probs.shape[-1]])
        next_sentence_predictions = tf.argmax(
            input=next_sentence_log_probs, axis=-1, output_type=tf.int32)
        next_sentence_labels = tf.reshape(next_sentence_labels, [-1])
        next_sentence_accuracy = tf.compat.v1.metrics.accuracy(
            labels=next_sentence_labels, predictions=next_sentence_predictions)
        next_sentence_mean_loss = tf.compat.v1.metrics.mean(
            values=next_sentence_example_loss)

        return {
            "masked_lm_accuracy": masked_lm_accuracy,
            "masked_lm_loss": masked_lm_mean_loss,
            "next_sentence_accuracy": next_sentence_accuracy,
            "next_sentence_loss": next_sentence_mean_loss,
        }

      eval_metrics = (metric_fn, [
          masked_lm_example_loss, masked_lm_log_probs, masked_lm_ids,
          masked_lm_weights, next_sentence_example_loss,
          next_sentence_log_probs, next_sentence_labels
      ])
      output_spec = tf.compat.v1.estimator.tpu.TPUEstimatorSpec(
          mode=mode,
          loss=total_loss,
          eval_metrics=eval_metrics,
          scaffold_fn=scaffold_fn)
    else:
      raise ValueError("Only TRAIN and EVAL modes are supported: %s" % (mode))

    return output_spec

  return model_fn


def get_masked_lm_output(bert_config, input_tensor, output_weights, positions,
                         label_ids, label_weights):
  """Get loss and log probs for the masked LM."""
  input_tensor = gather_indexes(input_tensor, positions)

  with tf.compat.v1.variable_scope("cls/predictions"):
    # We apply one more non-linear transformation before the output layer.
    # This matrix is not used after pre-training.
    with tf.compat.v1.variable_scope("transform"):
      input_tensor = tf.compat.v1.layers.dense(
          input_tensor,
          units=bert_config.hidden_size,
          activation=modeling.get_activation(bert_config.hidden_act),
          kernel_initializer=modeling.create_initializer(
              bert_config.initializer_range))
      input_tensor = modeling.layer_norm(input_tensor)

    # The output weights are the same as the input embeddings, but there is
    # an output-only bias for each token.
    output_bias = tf.compat.v1.get_variable(
        "output_bias",
        shape=[bert_config.vocab_size],
        initializer=tf.compat.v1.zeros_initializer())
    input_tensor = bf.i_cast(input_tensor)
    output_weights = bf.i_cast(output_weights)
    logits = tf.matmul(input_tensor, output_weights, transpose_b=True)
    logits = tf.nn.bias_add(logits, output_bias)
    log_probs = tf.nn.log_softmax(logits, axis=-1)

    label_ids = tf.reshape(label_ids, [-1])
    label_weights = tf.reshape(label_weights, [-1])

    one_hot_labels = tf.one_hot(
        label_ids, depth=bert_config.vocab_size, dtype=tf.float32)

    # The `positions` tensor might be zero-padded (if the sequence is too
    # short to have the maximum number of predictions). The `label_weights`
    # tensor has a value of 1.0 for every real prediction and 0.0 for the
    # padding predictions.
    per_example_loss = -tf.reduce_sum(input_tensor=log_probs * one_hot_labels, axis=[-1])
    numerator = tf.reduce_sum(input_tensor=label_weights * per_example_loss)
    denominator = tf.reduce_sum(input_tensor=label_weights) + 1e-5
    loss = numerator / denominator

  return (loss, per_example_loss, log_probs)


def get_next_sentence_output(bert_config, input_tensor, labels):
  """Get loss and log probs for the next sentence prediction."""

  # Simple binary classification. Note that 0 is "next sentence" and 1 is
  # "random sentence". This weight matrix is not used after pre-training.
  with tf.compat.v1.variable_scope("cls/seq_relationship"):
    output_weights = tf.compat.v1.get_variable(
        "output_weights",
        shape=[2, bert_config.hidden_size],
        initializer=modeling.create_initializer(bert_config.initializer_range))
    output_bias = tf.compat.v1.get_variable(
        "output_bias", shape=[2], initializer=tf.compat.v1.zeros_initializer())

    input_tensor = bf.i_cast(input_tensor)
    output_weights = bf.i_cast(output_weights)
    logits = tf.matmul(input_tensor, output_weights, transpose_b=True)
    logits = tf.nn.bias_add(logits, output_bias)
    log_probs = tf.nn.log_softmax(logits, axis=-1)
    labels = tf.reshape(labels, [-1])
    one_hot_labels = tf.one_hot(labels, depth=2, dtype=tf.float32)
    per_example_loss = -tf.reduce_sum(input_tensor=one_hot_labels * log_probs, axis=-1)
    loss = tf.reduce_mean(input_tensor=per_example_loss)
    return (loss, per_example_loss, log_probs)


def gather_indexes(sequence_tensor, positions):
  """Gathers the vectors at the specific positions over a minibatch."""
  sequence_shape = modeling.get_shape_list(sequence_tensor, expected_rank=3)
  batch_size = sequence_shape[0]
  seq_length = sequence_shape[1]
  width = sequence_shape[2]

  flat_offsets = tf.reshape(
      tf.range(0, batch_size, dtype=tf.int32) * seq_length, [-1, 1])
  flat_positions = tf.reshape(positions + flat_offsets, [-1])
  flat_sequence_tensor = tf.reshape(sequence_tensor,
                                    [batch_size * seq_length, width])
  output_tensor = tf.gather(flat_sequence_tensor, flat_positions)
  return output_tensor


def input_fn_builder(input_files,
                     max_seq_length,
                     batch_size,
                     max_predictions_per_seq,
                     is_training,
                     num_cpu_threads=4):
  """Creates an `input_fn` closure to be passed to TPUEstimator."""

  def input_fn(params):
    """The actual input function."""

    name_to_features = {
        "input_ids":
            tf.io.FixedLenFeature([max_seq_length], tf.int64),
        "input_mask":
            tf.io.FixedLenFeature([max_seq_length], tf.int64),
        "segment_ids":
            tf.io.FixedLenFeature([max_seq_length], tf.int64),
        "masked_lm_positions":
            tf.io.FixedLenFeature([max_predictions_per_seq], tf.int64),
        "masked_lm_ids":
            tf.io.FixedLenFeature([max_predictions_per_seq], tf.int64),
        "masked_lm_weights":
            tf.io.FixedLenFeature([max_predictions_per_seq], tf.float32),
        "next_sentence_labels":
            tf.io.FixedLenFeature([1], tf.int64),
    }

    # For training, we want a lot of parallel reading and shuffling.
    # For eval, we want no shuffling and parallel reading doesn't matter.
    if is_training:
      d = tf.data.Dataset.from_tensor_slices(tf.constant(input_files))
      d = d.repeat()
      d = d.shuffle(buffer_size=len(input_files))

      # `cycle_length` is the number of parallel files that get read.
      cycle_length = min(num_cpu_threads, len(input_files))

      # `sloppy` mode means that the interleaving is not exact. This adds
      # even more randomness to the training pipeline.
      d = d.apply(
          tf.data.experimental.parallel_interleave(
              tf.data.TFRecordDataset,
              sloppy=is_training,
              cycle_length=cycle_length))
      d = d.shuffle(buffer_size=100)
    else:
      d = tf.data.TFRecordDataset(input_files)
      # Since we evaluate for a fixed number of steps we don't want to encounter
      # out-of-range exceptions.
      d = d.repeat()

    # We must `drop_remainder` on training because the TPU requires fixed
    # size dimensions. For eval, we assume we are evaluating on the CPU or GPU
    # and we *don't* want to drop the remainder, otherwise we wont cover
    # every sample.
    d = d.apply(
        tf.data.experimental.map_and_batch(
            lambda record: _decode_record(record, name_to_features),
            batch_size=batch_size,
            num_parallel_batches=num_cpu_threads,
            drop_remainder=True))
    return d

  return input_fn


def _decode_record(record, name_to_features):
  """Decodes a record to a TensorFlow example."""
  example = tf.io.parse_single_example(serialized=record, features=name_to_features)

  # tf.Example only supports tf.int64, but the TPU only supports tf.int32.
  # So cast all int64 to int32.
  for name in list(example.keys()):
    t = example[name]
    if t.dtype == tf.int64:
      t = tf.cast(t, dtype=tf.int32)
    example[name] = t

  return example


def logBatchSizeInfo(FLAGS) :
    message1 = " Training batch size: " + str(FLAGS.train_batch_size)
    message2 = " Accumulation batch size: " + str(FLAGS.train_batch_size)
    message3 = " Accumulation steps: " + str(FLAGS.accum_steps)
    tf.compat.v1.logging.info(message1)
    tf.compat.v1.logging.info(message2)
    tf.compat.v1.logging.info(message3)

def main(_):
  learning_rate = FLAGS.learning_rate
  # If Horovod is successfully enabled
  if is_mpi:
    FLAGS.output_dir = FLAGS.output_dir if hvd.rank() == 0 else \
        os.path.join(FLAGS.output_dir, str(hvd.rank()))
    # Horovod: adjust number of steps based on number of CPUs.
    FLAGS.num_train_steps = FLAGS.num_train_steps // hvd.size()
    FLAGS.num_warmup_steps = FLAGS.num_warmup_steps // hvd.size()
    learning_rate = learning_rate * math.sqrt(hvd.size())

  tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.INFO)


  #if FLAGS.train_batch_size >32 :
  #  if FLAGS.train_batch_size % 32 != 0 :
  #    raise ValueError("If Batch size is > 32 it should be divisible by 32")
  #  else :
  #    FLAGS.accum_steps = int(FLAGS.train_batch_size/32)
  #    FLAGS.train_batch_size  = 32

  logBatchSizeInfo(FLAGS)

  if FLAGS.disable_v2_bevior:
    tf.compat.v1.disable_v2_behavior()

  if FLAGS.profile:
    tf.compat.v1.disable_eager_execution()

  if not FLAGS.do_train and not FLAGS.do_eval:
    raise ValueError("At least one of `do_train` or `do_eval` must be True.")

  bert_config = modeling.BertConfig.from_json_file(FLAGS.bert_config_file)
  bert_config.new_scope_settings(FLAGS.new_bf16_scope)
  bert_config.set_additional_options(FLAGS.precision, 
                                     FLAGS.experimental_gelu, 
                                     FLAGS.optimized_softmax)

  tf.io.gfile.makedirs(FLAGS.output_dir)

  input_files = []
  for input_pattern in FLAGS.input_file.split(","):
    input_files.extend(tf.io.gfile.glob(input_pattern))

  tf.compat.v1.logging.info("*** Input Files ***")
  for input_file in input_files:
    tf.compat.v1.logging.info("  %s" % input_file)

  tpu_cluster_resolver = None
  if FLAGS.use_tpu and FLAGS.tpu_name:
    tpu_cluster_resolver = tf.distribute.cluster_resolver.TPUClusterResolver(
        FLAGS.tpu_name, zone=FLAGS.tpu_zone, project=FLAGS.gcp_project)

  is_per_host = tf.compat.v1.estimator.tpu.InputPipelineConfig.PER_HOST_V2

  session_config = tf.compat.v1.ConfigProto(
      inter_op_parallelism_threads=FLAGS.inter_op_parallelism_threads,
      intra_op_parallelism_threads=FLAGS.intra_op_parallelism_threads,
      allow_soft_placement=True)
  if is_mpi:
    gpus = tf.config.experimental.list_physical_devices('XPU')
    for gpu in gpus:
      tf.config.experimental.set_memory_growth(gpu, True)
    if gpus:
      tf.config.experimental.set_visible_devices(gpus[hvd.local_rank()], 'XPU')
    session_config.gpu_options.visible_device_list = str(hvd.local_rank())
  run_config = tf.compat.v1.estimator.tpu.RunConfig(
      cluster=tpu_cluster_resolver,
      master=FLAGS.master,
      model_dir=FLAGS.output_dir,
      save_checkpoints_steps=FLAGS.save_checkpoints_steps,
      session_config=session_config,
      tpu_config=tf.compat.v1.estimator.tpu.TPUConfig(
          iterations_per_loop=FLAGS.iterations_per_loop,
          num_shards=FLAGS.num_tpu_cores,
          per_host_input_for_training=is_per_host),
      log_step_count_steps=1)

  if bert_config.precision == "bfloat16" :
    tf.compat.v1.logging.info("INFO: BERT bfloat16 training....!")
  else :
    tf.compat.v1.logging.info("INFO: BERT fp32 training....!")

  if bert_config.precision == "bfloat16" and bert_config.new_bf16_scope == False:
    with tf.compat.v1.tpu.bfloat16_scope():
      bf.set_global_precision(tf.bfloat16)
      tf.compat.v1.logging.info("*** Old bfloat16 scope set***")
      model_fn = model_fn_builder(
          bert_config=bert_config,
          init_checkpoint=FLAGS.init_checkpoint,
          learning_rate=learning_rate,
          num_train_steps=FLAGS.num_train_steps,
          num_warmup_steps=FLAGS.num_warmup_steps,
          accum_steps=FLAGS.accum_steps,
          use_tpu=FLAGS.use_tpu,
          use_one_hot_embeddings=FLAGS.use_tpu,
          use_multi_cpu=is_mpi)
  else :
    model_fn = model_fn_builder(
          bert_config=bert_config,
          init_checkpoint=FLAGS.init_checkpoint,
          learning_rate=learning_rate,
          num_train_steps=FLAGS.num_train_steps,
          num_warmup_steps=FLAGS.num_warmup_steps,
          accum_steps=FLAGS.accum_steps,
          use_tpu=FLAGS.use_tpu,
          use_one_hot_embeddings=FLAGS.use_tpu,
          use_multi_cpu=is_mpi)

  # If TPU is not available, this will fall back to normal Estimator on CPU
  # or GPU.
  estimator = tf.compat.v1.estimator.tpu.TPUEstimator(
      use_tpu=FLAGS.use_tpu,
      model_fn=model_fn,
      config=run_config,
      train_batch_size=FLAGS.train_batch_size*FLAGS.accum_steps,
      eval_batch_size=FLAGS.eval_batch_size)

  if FLAGS.do_train:
    tf.compat.v1.logging.info("***** Running training *****")
    tf.compat.v1.logging.info("  Batch size = %d", FLAGS.train_batch_size)
    train_input_fn = input_fn_builder(
        input_files=input_files,
        batch_size=FLAGS.train_batch_size,
        max_seq_length=FLAGS.max_seq_length,
        max_predictions_per_seq=FLAGS.max_predictions_per_seq,
        is_training=True)
    # Horovod: In the case of multi CPU training with Horovod, adding
    # hvd.BroadcastGlobalVariablesHook(0) hook, broadcasts the initial variable
    # states from rank 0 to all other processes. This is necessary to ensure
    # consistent initialization of all workers when training is started with
    # random weights or restored from a checkpoint.
    if is_mpi:
        hooks = [hvd.BroadcastGlobalVariablesHook(0)]
    else:
        hooks = []

    # TODO: support horovod hook
    if FLAGS.profile:
      tf.compat.v1.logging.info("***** Running training with profiler*****")
      hooks.append(tf.compat.v1.train.ProfilerHook(save_steps=3, output_dir=FLAGS.output_dir,
                                                   show_memory=False))
    hooks.append(LoggerHook(FLAGS.train_batch_size, False))

    estimator.train(input_fn=train_input_fn, max_steps=FLAGS.num_train_steps,
                    hooks=hooks)

  if FLAGS.do_eval:
    tf.compat.v1.logging.info("***** Running evaluation *****")
    tf.compat.v1.logging.info("  Batch size = %d", FLAGS.eval_batch_size)

    eval_input_fn = input_fn_builder(
        input_files=input_files,
        batch_size=FLAGS.train_batch_size,
        max_seq_length=FLAGS.max_seq_length,
        max_predictions_per_seq=FLAGS.max_predictions_per_seq,
        is_training=False)

    result = estimator.evaluate(
        input_fn=eval_input_fn, steps=FLAGS.max_eval_steps)

    output_eval_file = os.path.join(FLAGS.output_dir, "eval_results.txt")
    with tf.io.gfile.GFile(output_eval_file, "w") as writer:
      tf.compat.v1.logging.info("***** Eval results *****")
      for key in sorted(result.keys()):
        tf.compat.v1.logging.info("  %s = %s", key, str(result[key]))
        writer.write("%s = %s\n" % (key, str(result[key])))


if __name__ == "__main__":
  flags.mark_flag_as_required("input_file")
  flags.mark_flag_as_required("bert_config_file")
  flags.mark_flag_as_required("output_dir")
  tf.compat.v1.app.run()
