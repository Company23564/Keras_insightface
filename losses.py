import tensorflow as tf
import numpy as np
import os
import tensorflow.keras.backend as K


# margin_softmax class wrapper
class MarginSoftmax(tf.keras.losses.Loss):
    def __init__(self, power=2, scale=0.4, scale_all=1.0, from_logits=False, label_smoothing=0, **kwargs):
        super(MarginSoftmax, self).__init__(**kwargs)
        self.power, self.scale, self.from_logits, self.label_smoothing = power, scale, from_logits, label_smoothing
        self.scale_all = scale_all
        if power != 1 and scale == 0:
            self.logits_reduction_func = lambda xx: xx ** power
        elif power == 1 and scale != 0:
            self.logits_reduction_func = lambda xx: xx * scale
        else:
            self.logits_reduction_func = lambda xx: (xx ** power + xx * scale) / 2

    def call(self, y_true, y_pred):
        # margin_soft = tf.where(tf.cast(y_true, dtype=tf.bool), (y_pred ** self.power + y_pred * self.scale) / 2, y_pred)
        margin_soft = tf.where(tf.cast(y_true, dtype=tf.bool), self.logits_reduction_func(y_pred), y_pred) * self.scale_all
        return tf.keras.losses.categorical_crossentropy(
            y_true, margin_soft, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )

    def get_config(self):
        config = super(MarginSoftmax, self).get_config()
        config.update(
            {
                "power": self.power,
                "scale": self.scale,
                "scale_all": self.scale_all,
                "from_logits": self.from_logits,
                "label_smoothing": self.label_smoothing,
            }
        )
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


# ArcfaceLoss class
class ArcfaceLoss(tf.keras.losses.Loss):
    def __init__(self, margin1=1.0, margin2=0.5, margin3=0.0, scale=64.0, from_logits=True, label_smoothing=0, **kwargs):
        # reduction = tf.keras.losses.Reduction.NONE if tf.distribute.has_strategy() else tf.keras.losses.Reduction.AUTO
        # super(ArcfaceLoss, self).__init__(**kwargs, reduction=reduction)
        super(ArcfaceLoss, self).__init__(**kwargs)
        self.margin1, self.margin2, self.margin3, self.scale = margin1, margin2, margin3, scale
        self.from_logits, self.label_smoothing = from_logits, label_smoothing
        self.threshold = np.cos((np.pi - margin2) / margin1)  # grad(theta) == 0
        self.theta_min = (-1 - margin3) * 2
        # self.reduction_func = tf.keras.losses.CategoricalCrossentropy(
        #     from_logits=from_logits, label_smoothing=label_smoothing, reduction=reduction
        # )

    def call(self, y_true, norm_logits):
        # norm_logits = y_pred
        pick_cond = tf.cast(y_true, dtype=tf.bool)
        y_pred_vals = norm_logits[pick_cond]
        if self.margin1 == 1.0 and self.margin2 == 0.0 and self.margin3 == 0.0:
            theta = y_pred_vals
        elif self.margin1 == 1.0 and self.margin3 == 0.0:
            theta = tf.cos(tf.acos(y_pred_vals) + self.margin2)
        else:
            theta = tf.cos(tf.acos(y_pred_vals) * self.margin1 + self.margin2) - self.margin3
            # Grad(theta) == 0
            #   ==> np.sin(np.math.acos(xx) * margin1 + margin2) == 0
            #   ==> np.math.acos(xx) * margin1 + margin2 == np.pi
            #   ==> xx == np.cos((np.pi - margin2) / margin1)
            #   ==> theta_min == -1 - margin3
        theta_valid = tf.where(y_pred_vals > self.threshold, theta, self.theta_min - theta)
        theta_one_hot = tf.expand_dims(theta_valid - y_pred_vals, 1) * tf.cast(y_true, dtype=tf.float32)
        arcface_logits = (theta_one_hot + norm_logits) * self.scale
        # theta_one_hot = tf.expand_dims(theta_valid, 1) * tf.cast(y_true, dtype=tf.float32)
        # arcface_logits = tf.where(pick_cond, theta_one_hot, norm_logits) * self.scale
        # tf.assert_equal(tf.math.is_nan(tf.reduce_mean(arcface_logits)), False)
        return tf.keras.losses.categorical_crossentropy(
            y_true, arcface_logits, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )
        # return self.reduction_func(y_true, arcface_logits)

    def get_config(self):
        config = super(ArcfaceLoss, self).get_config()
        config.update(
            {
                "margin1": self.margin1,
                "margin2": self.margin2,
                "margin3": self.margin3,
                "scale": self.scale,
                "from_logits": self.from_logits,
                "label_smoothing": self.label_smoothing,
            }
        )
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


# ArcfaceLoss simple
class ArcfaceLossSimple(tf.keras.losses.Loss):
    def __init__(self, margin=0.5, scale=64.0, from_logits=True, label_smoothing=0, **kwargs):
        super(ArcfaceLossSimple, self).__init__(**kwargs)
        self.margin, self.scale, self.from_logits, self.label_smoothing = margin, scale, from_logits, label_smoothing
        self.margin_cos, self.margin_sin = tf.cos(margin), tf.sin(margin)
        self.threshold = tf.cos(np.pi - margin)
        self.low_pred_punish = tf.sin(np.pi - margin) * margin

    def call(self, y_true, norm_logits):
        pick_cond = tf.cast(y_true, dtype=tf.bool)
        y_pred_vals = norm_logits[pick_cond]
        theta = y_pred_vals * self.margin_cos - tf.sqrt(1 - tf.pow(y_pred_vals, 2)) * self.margin_sin
        theta_valid = tf.where(y_pred_vals > self.threshold, theta, y_pred_vals - self.low_pred_punish)
        theta_one_hot = tf.expand_dims(theta_valid, 1) * tf.cast(y_true, dtype=tf.float32)
        arcface_logits = tf.where(pick_cond, theta_one_hot, norm_logits) * self.scale
        return tf.keras.losses.categorical_crossentropy(
            y_true, arcface_logits, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )

    def get_config(self):
        config = super(ArcfaceLossSimple, self).get_config()
        config.update(
            {
                "margin": self.margin,
                "scale": self.scale,
                "from_logits": self.from_logits,
                "label_smoothing": self.label_smoothing,
            }
        )
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


# [CurricularFace: Adaptive Curriculum Learning Loss for Deep Face Recognition](https://arxiv.org/pdf/2004.00288.pdf)
class CurricularFaceLoss(ArcfaceLossSimple):
    def __init__(self, margin=0.5, scale=64.0, from_logits=True, label_smoothing=0, **kwargs):
        super(CurricularFaceLoss, self).__init__(margin, scale, from_logits, label_smoothing, **kwargs)
        self.hard_example_scale = tf.Variable(0, dtype="float32")

    def call(self, y_true, norm_logits):
        pick_cond = tf.cast(y_true, dtype=tf.bool)
        y_pred_vals = norm_logits[pick_cond]
        theta = y_pred_vals * self.margin_cos - tf.sqrt(1 - tf.pow(y_pred_vals, 2)) * self.margin_sin
        theta_valid = tf.where(y_pred_vals > self.threshold, theta, y_pred_vals - self.low_pred_punish)

        self.hard_example_scale.assign(tf.reduce_mean(y_pred_vals) * 0.01 + (1 - 0.01) * self.hard_example_scale)
        tf.print(", hard_example_scale =", self.hard_example_scale, end="")
        hard_norm_logits = tf.where(
            norm_logits > tf.expand_dims(theta, 1), norm_logits * (self.hard_example_scale + norm_logits), norm_logits
        )

        theta_one_hot = tf.expand_dims(theta_valid, 1) * tf.cast(y_true, dtype=tf.float32)
        logits = tf.where(pick_cond, theta_one_hot, hard_norm_logits) * self.scale
        return tf.keras.losses.categorical_crossentropy(
            y_true, logits, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )


# [CosFace: Large Margin Cosine Loss for Deep Face Recognition](https://arxiv.org/pdf/1801.09414.pdf)
class CosFaceLoss(ArcfaceLossSimple):
    def __init__(self, margin=0.35, scale=64.0, from_logits=True, label_smoothing=0, **kwargs):
        super(CosFaceLoss, self).__init__(margin, scale, from_logits, label_smoothing, **kwargs)

    def call(self, y_true, norm_logits):
        pick_cond = tf.cast(y_true, dtype=tf.bool)
        logits = tf.where(pick_cond, norm_logits - self.margin, norm_logits) * self.scale
        return tf.keras.losses.categorical_crossentropy(
            y_true, logits, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )


# [AdaCos: Adaptively Scaling Cosine Logits for Effectively Learning Deep Face Representations](https://arxiv.org/pdf/1905.00292.pdf)
class AdaCosLoss(tf.keras.losses.Loss):
    def __init__(self, num_classes, scale=0, max_median=np.pi / 4, from_logits=True, label_smoothing=0, **kwargs):
        super(AdaCosLoss, self).__init__(**kwargs)
        self.max_median, self.from_logits, self.label_smoothing = max_median, from_logits, label_smoothing
        self.num_classes = num_classes
        self.theta_med_max = tf.cast(max_median, "float32")
        if scale == 0:
            self.scale = tf.sqrt(2.0) * tf.math.log(float(num_classes) - 1)
        else:
            # In reload condition
            self.scale = tf.cast(scale, "float32")

    @tf.function
    def call(self, y_true, norm_logits):
        pick_cond = tf.cast(y_true, dtype=tf.bool)
        y_pred_vals = norm_logits[pick_cond]
        theta = tf.acos(y_pred_vals)
        med_pos = tf.shape(norm_logits)[0] // 2 - 1
        theta_med = tf.sort(theta)[med_pos]

        B_avg = tf.where(pick_cond, tf.zeros_like(norm_logits), tf.exp(self.scale * norm_logits))
        B_avg = tf.reduce_mean(tf.reduce_sum(B_avg, axis=1))
        self.scale = tf.math.log(B_avg) / tf.cos(tf.minimum(self.theta_med_max, theta_med))
        tf.print(", scale =", self.scale, ", theta_med =", theta_med, end="")

        arcface_logits = norm_logits * self.scale
        return tf.keras.losses.categorical_crossentropy(
            y_true, arcface_logits, from_logits=self.from_logits, label_smoothing=self.label_smoothing
        )
        # return self.reduction_func(y_true, arcface_logits)

    def get_config(self):
        config = super(AdaCosLoss, self).get_config()
        config.update(
            {
                "num_classes": self.num_classes,
                # "scale": self.scale.numpy(),
                "max_median": self.max_median,
                "from_logits": self.from_logits,
                "label_smoothing": self.label_smoothing,
            }
        )
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


# Callback to save center values on each epoch end
class Save_Numpy_Callback(tf.keras.callbacks.Callback):
    def __init__(self, save_file, save_tensor):
        super(Save_Numpy_Callback, self).__init__()
        self.save_file = os.path.splitext(save_file)[0]
        self.save_tensor = save_tensor

    def on_epoch_end(self, epoch=0, logs=None):
        np.save(self.save_file, self.save_tensor.numpy())


# [A Discriminative Feature Learning Approach for Deep Face Recognition](http://ydwen.github.io/papers/WenECCV16.pdf)
class CenterLoss(tf.keras.losses.Loss):
    def __init__(self, num_classes, emb_shape=512, alpha=0.5, initial_file=None, **kwargs):
        super(CenterLoss, self).__init__(**kwargs)
        self.num_classes, self.emb_shape, self.alpha = num_classes, emb_shape, alpha
        self.initial_file = initial_file
        centers = tf.Variable(tf.zeros([num_classes, emb_shape]), trainable=False, aggregation=tf.VariableAggregation.MEAN)
        # centers = tf.Variable(tf.random.truncated_normal((num_classes, emb_shape)), trainable=False, aggregation=tf.VariableAggregation.MEAN)
        if initial_file:
            if os.path.exists(initial_file):
                print(">>>> Reload from center backup:", initial_file)
                aa = np.load(initial_file)
                centers.assign(aa)
            self.save_centers_callback = Save_Numpy_Callback(initial_file, centers)
        self.centers = centers
        if tf.distribute.has_strategy():
            self.num_replicas = tf.distribute.get_strategy().num_replicas_in_sync
        else:
            self.num_replicas = 1

    def __calculate_center_loss__(self, centers_batch, embedding):
        return tf.reduce_sum(tf.square(embedding - centers_batch), axis=-1) / 2

    def call(self, y_true, embedding):
        # embedding = y_pred[:, : self.emb_shape]
        labels = tf.argmax(y_true, axis=1)
        centers_batch = tf.gather(self.centers, labels)
        # loss = tf.reduce_mean(tf.square(embedding - centers_batch))
        loss = self.__calculate_center_loss__(centers_batch, embedding)

        # Update centers
        diff = centers_batch - embedding
        unique_label, unique_idx, unique_count = tf.unique_with_counts(labels)
        appear_times = tf.cast(tf.gather(unique_count, unique_idx), tf.float32)

        # diff = diff / tf.expand_dims(appear_times, 1)
        diff = diff / tf.expand_dims(appear_times + 1, 1)  # Δcj
        diff = self.num_replicas * self.alpha * diff
        # print(centers_batch.shape, self.centers.shape, labels.shape, diff.shape)
        self.centers.assign(tf.tensor_scatter_nd_sub(self.centers, tf.expand_dims(labels, 1), diff))
        # centers_batch = tf.gather(self.centers, labels)
        return loss

    def get_config(self):
        config = super(CenterLoss, self).get_config()
        config.update(
            {
                "num_classes": self.num_classes,
                "emb_shape": self.emb_shape,
                "alpha": self.alpha,
                "initial_file": self.initial_file,
            }
        )
        return config

    @classmethod
    def from_config(cls, config):
        if "feature_dim" in config:
            config["emb_shape"] = config.pop("feature_dim")
        if "factor" in config:
            config.pop("factor")
        if "logits_loss" in config:
            config.pop("logits_loss")
        return cls(**config)


class CenterLossCosine(CenterLoss):
    def __calculate_center_loss__(self, centers_batch, embedding):
        norm_emb = tf.nn.l2_normalize(embedding, 1)
        norm_center = tf.nn.l2_normalize(centers_batch, 1)
        return 1 - tf.reduce_sum(norm_emb * norm_center, axis=-1)


# TripletLoss helper class definitions [Triplet Loss and Online Triplet Mining in TensorFlow](https://omoindrot.github.io/triplet-loss)
class TripletLossWapper(tf.keras.losses.Loss):
    def __init__(self, alpha=0.35, **kwargs):
        # reduction = tf.keras.losses.Reduction.NONE if tf.distribute.has_strategy() else tf.keras.losses.Reduction.AUTO
        # super(TripletLossWapper, self).__init__(**kwargs, reduction=reduction)
        super(TripletLossWapper, self).__init__(**kwargs)
        self.alpha = alpha

    def __calculate_triplet_loss__(self, y_true, y_pred, alpha):
        return None

    def call(self, labels, embeddings):
        return self.__calculate_triplet_loss__(labels, embeddings, self.alpha)

    def get_config(self):
        config = super(TripletLossWapper, self).get_config()
        config.update({"alpha": self.alpha})
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


class BatchHardTripletLoss(TripletLossWapper):
    def __calculate_triplet_loss__(self, labels, embeddings, alpha):
        labels = tf.argmax(labels, axis=1)
        # labels = tf.squeeze(labels)
        # labels.set_shape([None])
        pos_mask = tf.equal(tf.expand_dims(labels, 0), tf.expand_dims(labels, 1))
        norm_emb = tf.nn.l2_normalize(embeddings, 1)
        dists = tf.matmul(norm_emb, tf.transpose(norm_emb))
        # pos_dists = tf.ragged.boolean_mask(dists, pos_mask)
        pos_dists = tf.where(pos_mask, dists, tf.ones_like(dists))
        hardest_pos_dist = tf.reduce_min(pos_dists, -1)
        # neg_dists = tf.ragged.boolean_mask(dists, tf.logical_not(pos_mask))
        neg_dists = tf.where(pos_mask, tf.ones_like(dists) * -1, dists)
        hardest_neg_dist = tf.reduce_max(neg_dists, -1)
        basic_loss = hardest_neg_dist - hardest_pos_dist + alpha
        # ==> pos - neg > alpha
        # ==> neg + alpha - pos < 0
        # return tf.reduce_mean(tf.maximum(basic_loss, 0.0))
        return tf.maximum(basic_loss, 0.0)


class BatchHardTripletLossEuclidean(TripletLossWapper):
    def __calculate_triplet_loss__(self, labels, embeddings, alpha):
        labels = tf.argmax(labels, axis=1)
        pos_mask = tf.equal(tf.expand_dims(labels, 0), tf.expand_dims(labels, 1))
        # dense_mse_func = lambda xx: tf.reduce_sum(tf.square((embeddings - xx)), axis=-1)
        # dense_mse_func = tf.function(dense_mse_func, input_signature=(tf.TensorSpec(shape=[None], dtype=tf.float32),))
        # dists = tf.vectorized_map(dense_mse_func, embeddings)

        # Euclidean_dists = aa ** 2 + bb ** 2 - 2 * aa * bb, where aa = embeddings, bb = embeddings
        embeddings_sqaure_sum = tf.reduce_sum(tf.square(embeddings), axis=-1)
        ab = tf.matmul(embeddings, tf.transpose(embeddings))
        dists = tf.reshape(embeddings_sqaure_sum, (-1, 1)) + embeddings_sqaure_sum - 2 * ab
        # pos_dists = tf.ragged.boolean_mask(dists, pos_mask)
        pos_dists = tf.where(pos_mask, dists, tf.zeros_like(dists))
        hardest_pos_dist = tf.reduce_max(pos_dists, -1)
        # neg_dists = tf.ragged.boolean_mask(dists, tf.logical_not(pos_mask))
        neg_dists = tf.where(pos_mask, tf.ones_like(dists) * tf.reduce_max(dists), dists)
        hardest_neg_dist = tf.reduce_min(neg_dists, -1)
        tf.print(
            " - triplet_dists_mean:",
            tf.reduce_mean(dists),
            "pos:",
            tf.reduce_mean(hardest_pos_dist),
            "neg:",
            tf.reduce_mean(hardest_neg_dist),
            end="",
        )
        basic_loss = hardest_pos_dist + alpha - hardest_neg_dist
        # ==> neg - pos > alpha
        # ==> pos + alpha - neg < 0
        # return tf.reduce_mean(tf.maximum(basic_loss, 0.0))
        return tf.maximum(basic_loss, 0.0)


class BatchHardTripletLossEuclideanAutoAlpha(TripletLossWapper):
    def __init__(self, alpha=0.1, init_auto_alpha=1, **kwargs):
        # reduction = tf.keras.losses.Reduction.NONE if tf.distribute.has_strategy() else tf.keras.losses.Reduction.AUTO
        # super(TripletLossWapper, self).__init__(**kwargs, reduction=reduction)
        super(BatchHardTripletLossMSEAutoAlpha, self).__init__(alpha=alpha, **kwargs)
        self.auto_alpha = tf.Variable(init_auto_alpha, dtype="float", trainable=False)

    def __calculate_triplet_loss__(self, labels, embeddings, alpha):
        labels = tf.argmax(labels, axis=1)
        pos_mask = tf.equal(tf.expand_dims(labels, 0), tf.expand_dims(labels, 1))
        # dense_mse_func = lambda xx: tf.reduce_sum(tf.square((embeddings - xx)), axis=-1)
        # dense_mse_func = tf.function(dense_mse_func, input_signature=(tf.TensorSpec(shape=[None], dtype=tf.float32),))
        # dists = tf.vectorized_map(dense_mse_func, embeddings)

        # Euclidean_dists = aa ** 2 + bb ** 2 - 2 * aa * bb, where aa = embeddings, bb = embeddings
        embeddings_sqaure_sum = tf.reduce_sum(tf.square(embeddings), axis=-1)
        ab = tf.matmul(embeddings, tf.transpose(embeddings))
        dists = tf.reshape(embeddings_sqaure_sum, (-1, 1)) + embeddings_sqaure_sum - 2 * ab
        # pos_dists = tf.ragged.boolean_mask(dists, pos_mask)
        pos_dists = tf.where(pos_mask, dists, tf.zeros_like(dists))
        hardest_pos_dist = tf.reduce_max(pos_dists, -1)
        # neg_dists = tf.ragged.boolean_mask(dists, tf.logical_not(pos_mask))
        neg_dists = tf.where(pos_mask, tf.ones_like(dists) * tf.reduce_max(dists), dists)
        hardest_neg_dist = tf.reduce_min(neg_dists, -1)
        basic_loss = hardest_pos_dist + self.auto_alpha - hardest_neg_dist
        self.auto_alpha.assign(tf.reduce_mean(dists) * alpha)
        tf.print(
            " - triplet_dists_mean:",
            tf.reduce_mean(dists),
            "pos:",
            tf.reduce_mean(hardest_pos_dist),
            "neg:",
            tf.reduce_mean(hardest_neg_dist),
            "auto_alpha:",
            self.auto_alpha,
            end="",
        )
        # ==> neg - pos > alpha
        # ==> pos + alpha - neg < 0
        # return tf.reduce_mean(tf.maximum(basic_loss, 0.0))
        return tf.maximum(basic_loss, 0.0)


class BatchAllTripletLoss(TripletLossWapper):
    def __calculate_triplet_loss__(self, labels, embeddings, alpha):
        labels = tf.argmax(labels, axis=1)
        # labels = tf.squeeze(labels)
        # labels.set_shape([None])
        pos_mask = tf.equal(tf.expand_dims(labels, 0), tf.expand_dims(labels, 1))
        norm_emb = tf.nn.l2_normalize(embeddings, 1)
        dists = tf.matmul(norm_emb, tf.transpose(norm_emb))

        pos_dists = tf.where(pos_mask, dists, tf.ones_like(dists))
        pos_dists_loss = tf.reduce_sum(1.0 - pos_dists, -1) / tf.reduce_sum(tf.cast(pos_mask, dtype=tf.float32), -1)
        hardest_pos_dist = tf.expand_dims(tf.reduce_min(pos_dists, -1), 1)

        neg_valid_mask = tf.logical_and(tf.logical_not(pos_mask), (hardest_pos_dist - dists) < alpha)
        neg_dists_valid = tf.where(neg_valid_mask, dists, tf.zeros_like(dists))
        neg_dists_loss = tf.reduce_sum(neg_dists_valid, -1) / (tf.reduce_sum(tf.cast(neg_valid_mask, dtype=tf.float32), -1) + 1)
        return pos_dists_loss + neg_dists_loss


def distiller_loss_euclidean(true_emb, pred_emb):
    return tf.reduce_sum(tf.square(pred_emb - true_emb), axis=-1)


def distiller_loss_cosine(true_emb, pred_emb):
    true_emb_normed = tf.nn.l2_normalize(true_emb, axis=-1)
    pred_emb_normed = tf.nn.l2_normalize(pred_emb, axis=-1)
    loss = 1 - tf.reduce_sum(pred_emb_normed * true_emb_normed, axis=-1)
    return loss
