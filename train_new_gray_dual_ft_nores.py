# coding: utf-8
from __future__ import print_function
from __future__ import division
from data_parser.parse_tfrec import *
from loss.cal_loss import *
from utils.utilities import *
from utils.utils_lap_pyramid import *
from utils.configs import *
import net.net_new_structure as ns
import time, os, sys
from metrics_measurement.ssim import *
import matplotlib.pyplot as plt

"""
Fine-tuning the entire network including pre-trained high, bot layers and the ft layer.
"""

level = '4'
batchnum = config.train.batchnum_ft
model_ckp = config.model.ckp_path_ft
tfrecord_path = config.model.tfrecord_ft
height = 256
width = 256

tf.logging.set_verbosity(tf.logging.INFO)

os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"


def setconf(lev, lev_scale):
    global model_ckp, tfrecord_path
    if lev == 'high':
        model_ckp = config.model.ckp_path_high + config.model.ckp_lev_scale + lev_scale + '/'
    elif lev == 'bot':
        model_ckp = config.model.ckp_path_bot + config.model.ckp_lev_scale + lev_scale + '/'
    elif lev == 'ft':
        model_ckp = config.model.ckp_path_ft + config.model.ckp_lev_scale + lev_scale + '/'
        tfrecord_path = '/media/ict419/SSD/laval_train/' + 'ft_freq' + '_' + lev_scale + '_' + config.model.tfrecord_suffix
    else:
        sys.exit("Wrong requesting layer name!")


def evalfrontlayer(sess):
    """Read tfrecord"""
    train_iter = data_iterator_new_ft(tfrecord_path)
    high, bot, gt = train_iter.get_next()

    return high, bot, gt


def restoreftlayer(sess):
    high, bot, gt = evalfrontlayer(sess)

    """Feed Network"""
    out_h = ns.nethighlayer(high)
    '''
    variables_to_restore = []
    for v in tf.trainable_variables():
        if v.name.startswith('high'):
            variables_to_restore.append(v)

    setconf('high', lev_scale)
    saver = tf.train.Saver(variables_to_restore, write_version=tf.train.SaverDef.V2)
    ckpt = tf.train.get_checkpoint_state(model_ckp)
    if ckpt and ckpt.model_checkpoint_path:
        full_path = tf.train.latest_checkpoint(model_ckp)
        saver.restore(sess, full_path)
    '''
    out_b = ns.netbotlayer(bot)

    '''
    variables_to_restore = []
    for v in tf.trainable_variables():
        if v.name.startswith('bot'):
            variables_to_restore.append(v)

    setconf('bot', lev_scale)
    saver = tf.train.Saver(variables_to_restore, write_version=tf.train.SaverDef.V2)
    ckpt = tf.train.get_checkpoint_state(model_ckp)
    if ckpt and ckpt.model_checkpoint_path:
        full_path = tf.train.latest_checkpoint(model_ckp)
        saver.restore(sess, full_path)
    '''
    return out_h, out_b, high, bot, gt


def main(lev_scale, goal_epoch):
    setconf('ft', lev_scale)
    with tf.device('/device:GPU:0'):
        with tf.Graph().as_default():
            with tf.Session(config=tf.ConfigProto(log_device_placement=True)) as sess:

                output_high, output_bot, input_high, input_bot, gt = restoreftlayer(sess)

                h, w = calshape(height, width, lev_scale)
                tfbot_upsampling = tf.reshape(output_bot, [config.train.batch_size_ft, h, w])
                tfinputbot_upsampling = tf.reshape(input_bot, [config.train.batch_size_ft, h, w])

                new_bot = 0
                for index in range(config.train.batch_size_ft):
                    fullsize_bottom = tf.squeeze(tf.slice(tfbot_upsampling, [index, 0, 0], [1, -1, -1]))
                    fullsize_inputbottom = tf.squeeze(tf.slice(tfinputbot_upsampling, [index, 0, 0], [1, -1, -1]))

                    i = tf.constant(0)
                    n = tf.constant(int(lev_scale))
                    fullsize_bottom, _, _ = tf.while_loop(cond, body, [fullsize_bottom, i, n],
                                                          shape_invariants=[tf.TensorShape([None, None]), i.get_shape(),
                                                                            n.get_shape()])
                    fullsize_inputbottom, _, _ = tf.while_loop(cond, body, [fullsize_inputbottom, i, n],
                                                          shape_invariants=[tf.TensorShape([None, None]), i.get_shape(),
                                                                            n.get_shape()])

                    fullsize_bottom = tf.expand_dims(fullsize_bottom, axis=0)
                    fullsize_inputbottom = tf.expand_dims(fullsize_inputbottom, axis=0)
                    if index == 0:
                        new_bot = fullsize_bottom
                        input_bottom = fullsize_inputbottom
                    else:
                        new_bot = tf.concat([new_bot, fullsize_bottom], axis=0)
                        input_bottom = tf.concat([input_bottom, fullsize_inputbottom], axis=0)

                new_bot = tf.expand_dims(new_bot, axis=3)
                input_bottom = tf.expand_dims(input_bottom, axis=3)

                imgpatch = output_high + new_bot
                input = input_high + input_bottom

                loss, output, inputimg, _ = trainlayer(imgpatch, input, gt, sess)

                setconf('ft', lev_scale)
                summary = tf.summary.merge_all()
                writer = tf.summary.FileWriter(model_ckp, sess.graph)

                global_step = tf.Variable(0, name="global_step", trainable=False)

                variable_to_train = []
                for variable in tf.trainable_variables():
                    if not (variable.name.startswith(config.model.loss_model)):
                        variable_to_train.append(variable)
                train_op = tf.train.AdamOptimizer(1e-3).minimize(loss, global_step=global_step,
                                                                 var_list=variable_to_train)

                variables_to_restore = []
                for v in tf.global_variables():
                    if not (v.name.startswith(config.model.loss_model)):
                        variables_to_restore.append(v)
                saver = tf.train.Saver(variables_to_restore, write_version=tf.train.SaverDef.V2)
                sess.run([tf.global_variables_initializer(), tf.local_variables_initializer()])

                ''' restore high frequency vars '''
                variables_to_restore = []
                for v in tf.trainable_variables():
                    if v.name.startswith('high'):
                        variables_to_restore.append(v)

                setconf('high', lev_scale)
                saver_h = tf.train.Saver(variables_to_restore, write_version=tf.train.SaverDef.V2)
                ckpt = tf.train.get_checkpoint_state(model_ckp)
                if ckpt and ckpt.model_checkpoint_path:
                    full_path = tf.train.latest_checkpoint(model_ckp)
                    saver_h.restore(sess, full_path)

                ''' restore low frequency vars '''
                variables_to_restore = []
                for v in tf.trainable_variables():
                    if v.name.startswith('bot'):
                        variables_to_restore.append(v)

                setconf('bot', lev_scale)
                saver_l = tf.train.Saver(variables_to_restore, write_version=tf.train.SaverDef.V2)
                ckpt = tf.train.get_checkpoint_state(model_ckp)
                if ckpt and ckpt.model_checkpoint_path:
                    full_path = tf.train.latest_checkpoint(model_ckp)
                    saver_l.restore(sess, full_path)

                '''## debug
                aa, bb, cc, dd, gg = sess.run([output_high, new_bot, imgpatch, output, gt])
                aa = np.squeeze(aa)
                bb = np.squeeze(bb)
                cc = np.squeeze(cc)
                dd = np.squeeze(dd)
                gg = np.squeeze(gg)

                for i in range(config.train.batch_size_ft):
                    plt.figure(0)
                    plt.subplot(231)
                    plt.imshow(aa[i,:,:], cmap='gray')
                    plt.subplot(232)
                    plt.imshow(bb[i,:,:], cmap='gray')
                    plt.subplot(233)
                    plt.imshow(cc[i,:,:], cmap='gray')
                    plt.subplot(234)
                    plt.imshow(dd[i, :, :], cmap='gray')
                    plt.subplot(235)
                    plt.imshow(gg[i, :, :], cmap='gray')
                    plt.show()
                '''
                setconf('ft', lev_scale)
                # restore variables for training model if the checkpoint file exists.
                epoch = restoreandgetepochs(model_ckp, sess, batchnum, saver)

                '''## debug
                aa, bb, cc, dd, ee = sess.run([output_high, new_bot, imgpatch, output, gt])
                aa = np.squeeze(aa)
                bb = np.squeeze(bb)
                cc = np.squeeze(cc)
                dd = np.squeeze(dd)
                ee = np.squeeze(ee)

                for i in range(config.train.batch_size_ft):
                    plt.figure(0)
                    plt.subplot(231)
                    plt.imshow(aa[i,:,:], cmap='gray')
                    plt.subplot(232)
                    plt.imshow(bb[i,:,:], cmap='gray')
                    plt.subplot(233)
                    plt.imshow(cc[i,:,:], cmap='gray')
                    plt.subplot(234)
                    plt.imshow(dd[i, :, :], cmap='gray')
                    plt.subplot(235)
                    plt.imshow(ee[i, :, :], cmap='gray')
                    plt.show()
                '''

                ####################
                """Start Training"""
                ####################
                start_time = time.time()
                while True:
                    _, loss_t, step, predict, gtruth = sess.run([train_op, loss, global_step, output, gt])
                    batch_id = int(step % batchnum)
                    elapsed_time = time.time() - start_time
                    start_time = time.time()

                    """logging"""
                    tf.logging.info("Epoch: [%2d] [%4d/%4d] time: %4.4f, loss: %.6f, global step: %4d"
                                    % (epoch + 1, batch_id, batchnum, elapsed_time, loss_t, step))

                    # advance counters
                    if batch_id == 0:
                        if epoch >= goal_epoch:
                            break
                        else:
                            """checkpoint"""
                            saver.save(sess, os.path.join(model_ckp, 'pynets-model-ft.ckpt'), global_step=step)
                        epoch += 1

                    """summary"""
                    if step % 25 == 0:
                        tf.logging.info('adding summary...')
                        summary_str = sess.run(summary)
                        writer.add_summary(summary_str, step)
                        writer.flush()


def trainlayer(output, inputimg, gt, sess):

    '''l2 loss'''
    loss_l2 = tf.reduce_mean((output - gt)**2)

    '''perceptual loss'''
    # duplicate the colour channel to be 3 same layers.
    output_3_channels = tf.concat([output, output, output], axis=3)
    gt_gray_3_channels = tf.concat([gt, gt, gt], axis=3)

    losses = cal_loss(output_3_channels, gt_gray_3_channels, config.model.loss_vgg, sess)
    loss_f = losses.loss_f / 3

    # Calculate L2 Regularization value based on trainable weights in the network:
    weight_size = 0
    loss_l1_reg = 0
    for variable in tf.trainable_variables():
        if not (variable.name.startswith(config.model.loss_model)):
            loss_l1_reg += tf.reduce_sum(tf.abs(variable)) * 2
            weight_size += tf.size(variable)
    loss_l2_reg = loss_l1_reg / tf.to_float(weight_size)

    loss = loss_l2 * 0.6 + loss_f * 0.4 + loss_l2_reg * 0.2

    #################
    """Add Summary"""
    #################
    inputimg = tensor_norm_0_to_255(inputimg)
    output = tensor_norm_0_to_255(output)

    tf.summary.scalar('loss/loss_l2', loss_l2 * 0.6)
    tf.summary.scalar('loss/loss_f', loss_f * 0.4)
    tf.summary.scalar('loss/loss_l2_reg', loss_l2_reg * 0.2)
    tf.summary.scalar('loss/total_loss', loss)
    tf.summary.image('input', inputimg, max_outputs=12)
    tf.summary.image('output', output, max_outputs=12)
    tf.summary.image('ground_truth', gt, max_outputs=12)

    return loss, output, inputimg, gt


def load(ckpt_dir, sess, saver):
    tf.logging.info('reading checkpoint')
    ckpt = tf.train.get_checkpoint_state(ckpt_dir)
    if ckpt and ckpt.model_checkpoint_path:
        full_path = tf.train.latest_checkpoint(ckpt_dir)
        global_step = int(full_path.split('/')[-1].split('-')[-1])
        saver.restore(sess, full_path)
        return True, global_step
    else:
        return False, 0


def restoreandgetepochs(ckpt_dir, sess, batchnum, savaer):
    status, global_step = load(ckpt_dir, sess, savaer)
    if status:
        start_epoch = global_step // batchnum
        tf.logging.info('model restore success')
    else:
        start_epoch = 0
        tf.logging.info("[*] Not find pretrained model!")
    return start_epoch


def calshape(h, w, lev_scale):
    new_h, new_w = h, w
    for i in range(int(lev_scale)):
        new_h = int(new_h / 2)
        new_w = int(new_w / 2)
    return (new_h, new_w)


main(level, 2)

