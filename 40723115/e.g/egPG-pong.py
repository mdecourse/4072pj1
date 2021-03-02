""" Trains an agent with (stochastic) Policy Gradients on Pong. Uses OpenAI Gym. """
import numpy as np
import _pickle as pickle # 序列化使用者自定義的類別及實例
import gym

# hyperparameters
H = 200 # 隱藏層神經元數
batch_size = 10 #每多少個情節進行參數更新?
learning_rate = 1e-4#學習率
gamma = 0.99 # discount factor for reward
decay_rate = 0.99 # decay factor for RMSProp leaky sum of grad^2
resume = False # 從先前的檢查點回復?
render = False
# 模組初始化
D = 80 * 80  # 輸入維度:80x80網格
if resume:
    model = pickle.load(open('save.p', 'rb'))
else:
    model = {}
    #dn表格每個維度
    #返回值為指定維度的array
model['W1'] = np.random.randn(H, D) / np.sqrt(D)  # "Xavier" initialization
model['W2'] = np.random.randn(H) / np.sqrt(H)#randn函式返回一個或一組樣本，具有標準正態分佈。

grad_buffer = {k: np.zeros_like(v) for k, v in model.items()}  # update buffers that add up gradients over a batch
rmsprop_cache = {k: np.zeros_like(v) for k, v in model.items()}  # rmsprop memory
#壓縮功能到0和1之間
def sigmoid(x):
  return 1.0 / (1.0 + np.exp(-x)) # sigmoid "squashing" function to interval [0,1]
#
def prepro(I):
  """ prepro 210x160x3 uint8 frame into 6400 (80x80) 1D float vector """
  #將  210x160x3 uint8 frame 轉為 6400 (80x80) 1D 浮點向量
  I = I[35:195] # crop
  I = I[::2,::2,0] # downsample by factor of 2
  I[I == 144] = 0 # erase background (background type 1)
  I[I == 109] = 0 # erase background (background type 2)
  I[I != 0] = 1 # everything else (paddles, ball) just set to 1
  return I.astype(np.float).ravel()

def discount_rewards(r):
  """ take 1D float array of rewards and compute discounted reward """
#採取一為浮動獎勵數組並計算折扣獎勵
  discounted_r = np.zeros_like(r) #與r陣列型別一致的陣列
  running_add = 0
  for t in reversed(range(0, r.size)):
    if r[t] != 0: running_add = 0 # 重製總和, 因為這是遊戲邊界 (pong specific!)
    running_add = running_add * gamma + r[t]
    discounted_r[t] = running_add
  return discounted_r

def policy_forward(x):
  h = np.dot(model['W1'], x) #對於稱為1的數組，執行對應位置相乘，然後再相加，不為1的二維數組，執行矩陣乘法運算
  h[h<0] = 0 # ReLU nonlinearity
  logp = np.dot(model['W2'], h)
  p = sigmoid(logp)
  return p, h # 採取行動2的返回概率, 和隱藏層的狀態


def policy_backward(eph, epdlogp):
  """ backward pass. (eph is array of intermediate hidden states) """
#eph是中間隱藏狀態的數組
  dW2 = np.dot(eph.T, epdlogp).ravel()
  dh = np.outer(epdlogp, model['W2'])#求外積，如果是高維陣列，函式會將其自動轉成1維
  dh[eph <= 0] = 0 # backpro prelu
  dW1 = np.dot(dh.T, epx)
  return {'W1':dW1, 'W2':dW2}
env = gym.make("Pong-v0")
observation = env.reset()
prev_x = None # 用於計算差異幀
xs,hs,dlogps,drs = [],[],[],[]
running_reward = None
reward_sum = 0
episode_number = 0
while True:
  if render: env.render()

  # 對觀測值進行預處理, 將差異圖像設置為input
  cur_x = prepro(observation)
  x = cur_x - prev_x if prev_x is not None else np.zeros(D)
  prev_x = cur_x

  # forward the policy network and sample an action from the returned probability
  aprob, h = policy_forward(x)
  action = 2 if np.random.uniform() < aprob else 3 # roll the dice!

  # record various intermediates (needed later for backprop)
  xs.append(x) # observation #用於在列表末尾添加新的對象也就是x
  hs.append(h) # hidden state
  y = 1 if action == 2 else 0 # a "fake label"
  dlogps.append(y - aprob) # grad that encourages the action that was taken to be taken (see http://cs231n.github.io/neural-networks-2/#losses if confused)

  #步入環境並獲得新的測量結果
  observation, reward, done, info = env.step(action)
  reward_sum += reward

  drs.append(reward) # record reward (has to be done after we call step() to get reward for previous action)

  if done: # an episode finished
    episode_number += 1

    # 將episode的所有輸入，隱藏狀態，動作梯度和獎勵堆疊在一起
    # 沿著豎直方向將矩陣堆疊起來，除了第一維外，被堆疊的矩陣個維度要一致
    epx = np.vstack(xs)
    eph = np.vstack(hs)
    epdlogp = np.vstack(dlogps)
    epr = np.vstack(drs)
    xs,hs,dlogps,drs = [],[],[],[] # reset array memory

    # 向後計算折價獎勵
    discounted_epr = discount_rewards(epr)
    # standardize the rewards to be unit normal (helps control the gradient estimator variance)
    #將獎勵標準化為單位法線（幫助控制梯度估計量方差）
    discounted_epr -= np.mean(discounted_epr)
    discounted_epr /= np.std(discounted_epr) #計算標準差

    epdlogp *= discounted_epr # 靠著優勢調節梯度 (PG magic happens right here.)
    grad = policy_backward(eph, epdlogp)
    for k in model: grad_buffer[k] += grad[k] # 累積 grad over batch

    # perform rmsprop parameter update every batch_size episodes
    if episode_number % batch_size == 0:
      for k,v in model.items():
        g = grad_buffer[k] # gradient
        rmsprop_cache[k] = decay_rate * rmsprop_cache[k] + (1 - decay_rate) * g**2
        model[k] += learning_rate * g / (np.sqrt(rmsprop_cache[k]) + 1e-5)
        grad_buffer[k] = np.zeros_like(v) # 重置批次梯度buffer
        #print(grad_buffer['W1'])

    # boring book-keeping
    running_reward = reward_sum if running_reward is None else running_reward * 0.99 + reward_sum * 0.01
    print ('resetting env. episode reward total was %f. running mean: %f' % (reward_sum, running_reward))
    if episode_number % 100 == 0: pickle.dump(model, open('save.p', 'wb'))
    reward_sum = 0
    observation = env.reset() # reset env
    prev_x = None

  if reward != 0: # Pong has either +1 or -1 reward exactly when game ends.
    print ('ep %d: game finished, reward: %f' % (episode_number, reward) + ('' if reward == -1 else ' !!!!!!!!'))