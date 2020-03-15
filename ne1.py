from distutils.dir_util import copy_tree

import numpy as np
import tensorflow as tf
from gym.spaces import Box

import base


def softmax(x):
    """Compute softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()


def actor(dim=(10, 4)):
    inputs = tf.keras.layers.Input(dim)
    x = tf.keras.layers.GlobalAveragePooling1D()(inputs)
    x = tf.keras.layers.Dense(32, "elu", use_bias=False)(x)
    x = tf.keras.layers.Dense(32, "elu", use_bias=False)(x)
    x = tf.keras.layers.Dense(2, "tanh", use_bias=False)(x)

    return tf.keras.Model(inputs, x)


def output(x, name):
    x = tf.keras.layers.Dense(518, "elu")(x)
    return tf.keras.layers.Dense(1, name=name)(x)


def critic(dim):
    states = tf.keras.layers.Input(dim, name="states")
    action = tf.keras.layers.Input((2,), name="action")

    x = base.bese_net(states)

    x_action = tf.keras.layers.Concatenate()([x, action])
    q1 = output(x_action, "q1")
    q2 = output(x_action, "q2")
    v = output(x, "v")

    return tf.keras.Model([states, action], [q1, q2, v])


class Model(tf.keras.Model):
    def __init__(self, dim=(10, 4)):
        super(Model, self).__init__()
        self.actor = actor(dim)
        self.critic = critic(dim)


class Actor:
    def __init__(self, w):
        self.w = w
        self.fitness = 0


class NeuroEvolution:
    def __init__(self, population_size=100, mutation_rate=0.1, restore=False):
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self.restore = restore
        self.actor = actor

        self.n_winners = int(self.population_size * .4)
        self.n_parents = self.population_size - self.n_winners

        self.initialize()

    def initialize(self):
        self.population = np.array([Actor(np.array(actor().get_weights())) for _ in range(self.population_size)])
        if self.restore:
            w = np.load("ne1_w.npy")
            for i in range(self.population_size):
                self.population[i].w = w[i].copy()

    def mutate(self, individual, scale=1.0):
        for i in range(individual.shape[0]):
            mutation_mask = np.random.binomial(1, self.mutation_rate, individual.w[i].shape)
            individual.w[i] += np.random.normal(0, scale, individual[i].shape) * mutation_mask

    def inherit_weights(self, parent, child):
        child.w = parent.w.copy()
        return child

    def crossover(self, parent1, parent2):
        child1 = self.inherit_weights(parent1, Actor(np.array(actor().get_weights())))
        child2 = self.inherit_weights(parent2, Actor(np.array(actor().get_weights())))

        for i in range(parent1.shape[0]):
            cutoff = np.random.randint(0, parent1.w[i].shape[1])
            child1.w[i, :, cutoff:] = parent2.w[i, :, cutoff:].copy()
            child2.w[i, :, cutoff:] = parent1.w[i, :, cutoff:].copy()

        return child1, child2

    def evolve(self):
        fitnesses = np.array([i.fitness for i in self.population]).reshape((-1,))
        self.population = self.population[np.argsort(fitnesses)[::-1]]
        self.fittest_individual = self.population[0]

        next_population = self.population[:self.n_winners]
        probs = softmax(np.abs(fitnesses) / np.sum(np.abs(fitnesses)) * (np.abs(fitnesses) / fitnesses))
        parents = np.random.choice(self.population, self.n_parents, False, probs)

        for i in range(0, len(parents), 2):
            child1, child2 = self.crossover(parents[i], parents[i + 1])
            next_population += [self.mutate(child1), self.mutate(child2)]
        self.population = next_population


class Agent(base.Base_Agent):
    def build(self):
        self.ne = NeuroEvolution(restore=self.restore)

        self.gamma = 0.
        self.epoch = 0
        self.types = "PG"
        self.aciton_space = Box(-1, 1, (2,))

        self.model = Model()
        self.target_model = Model()

        if self.restore:
            self.i = np.load("ne1_epoch.npy")
            self.model.load_weights("ne1")
            self.target_model.load_weights("ne1")
        else:
            self.target_model.set_weights(self.model.get_weights())

        self.v_opt = tf.keras.optimizers.Nadam(self.lr)

    def sample(self, memory):
        states = np.array([a[0] for a in memory], np.float32)
        new_states = np.array([a[3] for a in memory], np.float32)
        actions = np.array([a[1] for a in memory]).reshape((-1, 2))
        rewards = np.array([a[2] for a in memory], np.float32).reshape((-1, 1))

        q1, q2, _ = self.model.critic.predict_on_batch([states, actions])
        q = (q1 + q2) / 2
        _, _, target_v = self.target_model.critic.predict_on_batch([states, actions])

        q_backup = rewards + self.gamma * target_v

        return self.huber_loss(q_backup, q).numpy()

    def train(self):
        tree_idx, replay = self.memory.sample(128)

        states = np.array([a[0][0] for a in replay], np.float32)
        new_states = np.array([a[0][3] for a in replay], np.float32)
        actions = np.array([a[0][1] for a in replay]).reshape((-1, 2))
        rewards = np.array([a[0][2] for a in replay], np.float32).reshape((-1, 1))

        policy = self.model.actor.predict_on_batch(states)
        q1_pi, q2_pi, _ = self.model.critic.predict_on_batch([states, policy])
        mean_q_pi = np.mean(q1_pi + q2_pi) / 2

        with tf.GradientTape() as tape:
            _, _, target_v = self.target_model.critic.predict_on_batch([new_states, actions])
            q1, q2, v = self.model.critic.predict_on_batch([states, actions])

            q_backup = rewards + self.gamma * target_v

            q1_loss = tf.reduce_mean(self.huber_loss(q_backup, q1))
            q2_loss = tf.reduce_mean(self.huber_loss(q_backup, q2))

            v_backup = mean_q_pi
            v_loss = tf.reduce_mean(self.huber_loss(v_backup, v))

            v_loss += q1_loss + q2_loss

        if self.epoch >= 50 and self.epoch % 2 == 0:
            for i in range(self.ne.population_size):
                self.model.actor.set_weights(self.ne.population[i].w)
                policy = self.model.actor.predict_on_batch(states)
                q1_pi, q2_pi = self.model.critic.predict_on_batch([states, policy])
                self.ne.population[i].fitness = np.mean(q1_pi + q2_pi) / 2

            self.ne.evolve()
            self.model.actor.set_weights(self.ne.fittest_individual)

            self.target_model.set_weights(
                (1 - 0.005) * np.array(self.target_model.get_weights()) + 0.005 * np.array(
                    self.model.get_weights()))

        gradients = tape.gradient(v_loss, self.model.critic.trainable_variables)
        gradients = [(tf.clip_by_value(grad, -10.0, 10.0))
                     for grad in gradients]
        self.v_opt.apply_gradients(zip(gradients, self.model.critic.trainable_variables))

    def lr_decay(self, i):
        lr = self.lr * 0.0001 ** (i / 10000000)
        self.v_opt.lr.assign(lr)

    def gamma_updae(self, i):
        self.gamma = 1 - (0.8 + (1 - 0.8) * (np.exp(-0.00001 * i)))

    def policy(self, state, i):
        if i > 100:
            policy = self.model.actor.predict_on_batch(state)
            if (i + 1) % 5 != 0:
                epislon = .1 if self.random % 5 != 0 else .5
                policy += epislon * np.random.randn(policy.shape[0], policy.shape[1])
                epislon = 0. if self.random % 5 != 0 else .5
                policy = np.array([policy[i] if epislon < np.random.rand() else self.aciton_space.sample() for i in
                                   range(policy.shape[0])])
                self.random += 1
        else:
            policy = np.array([self.aciton_space.sample() for _ in range(state.shape[0])])

        return policy

    def save(self, i):
        self.restore = True
        self.i = i
        self.model.save_weights("ne1/ne1")
        np.save("ne1/ne1_epoch", i)
        w = np.array([i.w for i in self.ne.population])
        np.save("ne1/ne1_w", w)
        copy_tree("/content/ne1", "/content/drive/My Drive")
