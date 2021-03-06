from collections import deque

import tensorflow as tf
from IPython.display import clear_output

from memory import Memory
from new_rewards import Reward, Reward2
import numpy as np
import random

# huber loss

def bese_net(inputs):
    x1 = tf.keras.layers.Conv1D(32, 3, padding="same", activation="elu")(inputs)
    x2 = tf.keras.layers.Conv1D(32, 3, dilation_rate=2, padding="same", activation="elu")(inputs)
    x3 = tf.keras.layers.Conv1D(32, 3, dilation_rate=4, padding="same", activation="elu")(inputs)
    x4 = tf.keras.layers.Conv1D(32, 3, dilation_rate=6, padding="same", activation="elu")(inputs)
    # x5 = tf.keras.layers.Conv1D(32, 3, dilation_rate=5, padding="same", activation="elu")(inputs)
    x6 = tf.keras.layers.Conv1D(32, 3, dilation_rate=6, padding="same", activation="elu")(inputs)
    x7 = tf.keras.layers.Conv1D(32, 3, dilation_rate=7, padding="same", activation="elu")(inputs)
    x8 = tf.keras.layers.Conv1D(32, 3, dilation_rate=8, padding="same", activation="elu")(inputs)
    # x = tf.keras.layers.Concatenate()([x1, x2, x3, x4])# + x5 + x6
    x = x1 + x2 + x3+ x4# + x5 + x6 + x7 + x8
    b = tf.keras.layers.Conv1D(32, 1, padding="same", activation="elu")(inputs)
    x = tf.keras.layers.Concatenate()([x, b])
    #
    x = tf.keras.layers.Conv1D(128, 3, padding="same", activation="elu")(x)

    x = tf.keras.layers.Flatten()(x)
    # x = tf.keras.layers.GlobalAveragePooling1D()(x)
    return x

class Base_Agent:
    def __init__(self, spread, pip_cost, leverage=500, min_lots=0.01, assets=1000000, available_assets_rate=0.4,
                 restore=False, step_size=96, n=3, lr=1-3):
        self.step_size = step_size
        spread /= pip_cost
        self.restore = restore
        self.lr = lr
        self.n = n
        self.gamma = 0.4
        self.random = 0

        self.gen_data()
        self.build()

        self.rewards = Reward(spread, leverage, pip_cost, min_lots, assets, available_assets_rate) if self.types == "DQN" else Reward2(spread, leverage, pip_cost, min_lots, assets, available_assets_rate)
        self.rewards.max_los_cut = -np.mean(self.atr) * pip_cost
        self.rewards.lc = -np.mean(self.atr) * pip_cost
        self.rewards.tp = np.abs(self.rewards.lc)
        self.memory = Memory(5000000)

    def build(self):
        pass

    def gen_data(self):
        self.x = np.load("x.npy")
        self.y, self.atr, self.scale_atr, self.high, self.low = np.load("target.npy")

    def mse(self, q_backup, q):
        return tf.abs(q_backup - q) ** 1.5

    def huber_loss(self, q_backup, q, delta=4):
        error = tf.abs(q_backup - q)
        loss = tf.where(error < delta, error ** 2 * .5, delta * error - 0.5 * delta ** 2)
        # return tf.where(q_backup > 0, loss, loss*0)
        return loss

    def loss(self, states, new_states, rewards, actions):
        pass

    def sample(self, memory):
        pass

    def train(self):
        pass

    def lr_decay(self, i):
        pass

    def gamma_updae(self, i):
        pass

    def nstep(self, r):
        discount_r = 0.0
        for r in r:
            discount_r += 0.99 * r
        return r

    def prob(self, history):
        prob = np.asanyarray(history)
        a = np.mean(prob == 0)
        b = np.mean(prob == 1)
        c = 1 - (a + b)
        prob = [a, b, c]
        return prob

    def policy(self, state, i):
        pass

    def pg_action(self, action):
        q = action[:]
        action, leverage = action[:, 0], [i * 2.5 if i > 0 else i * .5 for i in action[:, 1]]
        action = [0 if i > 0.5 else 1 for i in action]
        return action, leverage, q

    def save(self, i):
        pass

    def run(self, train=True):
        i = 10000000 if train else 6
        start = 0 if not self.restore else self.i
        start = start if train else i-1
        reset = 0
        h = np.random.randint(self.x.shape[0] - self.x.shape[0] * 0.2 - self.step_size)

        for i in range(start, i):
            if (i + 1) % 5 == 0:
                h = np.random.randint(
                    self.x.shape[0] - self.x.shape[0] * 0.2, self.x.shape[0] - self.step_size * 5)
            elif i % 5 != 0:
                h = np.random.randint(self.x.shape[0] - self.x.shape[0] * 0.2 - self.step_size)

            df = self.x[h:h + self.step_size]
            trend = self.y[h:h + self.step_size]
            atr = self.atr[h:h + self.step_size]
            scale_atr = self.scale_atr[h:h + self.step_size]
            high = self.high[h:h + self.step_size]
            low = self.low[h:h + self.step_size]

            memory = deque()

            action = self.policy(df, i)
            if self.types == "PG":
                action, leverage, lc, tp, q = self.pg_action(action)
                self.rewards.reward(trend, high, low, action, leverage, lc, tp, atr, scale_atr)
            elif self.types == "DQN":
                self.rewards.reward(trend, high, low, action, atr, scale_atr)
                q = action

            if (reset + 1) % 10000 == 0:
                self.memory = Memory(5000000)
                reset = 0

            # memory append
            if (i + 1) % 5 != 0 and self.rewards.growth_rate:
                rewards = np.zeros(len(self.rewards.growth_rate))
                for index, r in enumerate(self.rewards.total_gain):
                    if index == 0:
                        rewards[index] = 0
                    else:
                        # rewards[index] = r - self.rewards.total_gain[index - 1]
                        rewards[index] = (np.log(r / self.rewards.total_gain[index - 1]) * 100)
                        rewards[index] = int(rewards[index] * 10 ** 3) * (10 ** -2)
                        # if rewards[index] == -np.inf:
                        #     rewards[index] = 0

                rewards = rewards.astype(np.float32)

                for t in range(0, len(trend) - 1):
                    tau = t - self.n + 1
                    if tau >= 0:
                        r = self.nstep(rewards[tau + 1:tau + self.n])
                        memory.append((df[tau], q[tau], r, df[tau + self.n]))
                    self.mem = memory

                memory = random.sample(memory, int(self.step_size * 0.5))
                ae = self.sample(memory).reshape((-1,))

                for e in range(len(ae)):
                    self.memory.store(memory[e], ae[e])

            if reset > 50:
                self.train()
            self.lr_decay(i)
            self.gamma_updae(i)

            reset += 1

            if i % 2000 == 0:
                clear_output()

            if (i + 1) % 5 == 0:
                prob = self.prob(action)

                print('action probability: buy={}, sell={}, hold={}'.format(
                    prob[0], prob[1], prob[2]))
                print('epoch: {}, total assets:{}, growth_rate:{}'.format(
                    i + 1, self.rewards.assets, self.rewards.assets / self.rewards.initial_assets))
                print("")

            if (i + 1) % 500 == 0:
                self.save(i)

            self.rewards.reset()