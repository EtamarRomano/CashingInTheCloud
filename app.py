from flask import Flask, request
import boto3
import xxhash
import json
from datetime import datetime
import requests
from requests.exceptions import Timeout
import jump

app = Flask(__name__)
dynamodb = boto3.resource('dynamodb', region_name="us-east-1")
AliveTable = dynamodb.Table('ImAlive')
IpAddress = ""
cache = {}
aliveInterval = 2 * 1000  # 2 seconds in millis

amountOfLivingNodes = 1
liveNodesList = []


def convertToMillisec(time):
    return int(round(time.timestamp() * 1000))  # turn into hundredth of a sec?


@app.route('/health-check', methods=['GET', 'POST'])
def health_check():
    currentTime = convertToMillisec(datetime.now())  # current time in milliSeconds
    healthSign = {'name': IpAddress,
                  'lastTimeAlive': currentTime}
    AliveTable.put_item(Item=healthSign)
    currentLiveNodesList = getAllAliveInstances()
    currentAliveNodes = len(currentLiveNodesList)
    if currentAliveNodes != amountOfLivingNodes:
        changePartitionOfData(currentAliveNodes, currentLiveNodesList)
    return f'my name is {IpAddress} at time {currentTime}'


# if topology of node changes, keep consistent hashing
def changePartitionOfData(currentNumOfNodes, currentLiveNodesList):
    global liveNodesList
    global amountOfLivingNodes
    for virtualKey in cache:
        node, altNode, oldNode, oldAltNode = getOldAndNewTargetNodes(currentNumOfNodes, currentLiveNodesList, virtualKey)
        flag = False
        if (node != oldNode) or (altNode != oldAltNode):
            flag = True
        if flag is True:  # change partition of the data if needed
            virtualNode = cache.pop(virtualKey)
            for key in virtualNode:
                data, expirationDate = virtualNode[key]
                if node == IpAddress:
                    addToCache(key, data, virtualKey, expirationDate)
                else:
                    requests.post(createURL('put', altNode, key, virtualKey, data, expirationDate)).json()
                if altNode == IpAddress:
                    addToCache(key, data, virtualKey, expirationDate)
                else:
                    requests.post(createURL('put', altNode, key, virtualKey, data, expirationDate)).json()
    liveNodesList = currentLiveNodesList
    amountOfLivingNodes = currentNumOfNodes


def getOldAndNewTargetNodes(currentNumOfNodes, currentLiveNodesList, virtualKey):
    newNodeIndex = jump.hash(int(virtualKey), currentNumOfNodes)
    newAltNodeIndex = (newNodeIndex + 1) % currentNumOfNodes
    oldNodeIndex = jump.hash(int(virtualKey), amountOfLivingNodes)
    oldAltNodeIndex = (oldNodeIndex + 1) % amountOfLivingNodes

    node = currentLiveNodesList[newNodeIndex]
    altNode = currentLiveNodesList[newAltNodeIndex]
    oldNode = liveNodesList[oldNodeIndex]
    oldAltNode = liveNodesList[oldAltNodeIndex]
    return node, altNode, oldNode, oldAltNode


def getAllAliveInstances():  # as explained in the last session
    nowInMilli = convertToMillisec(datetime.now())
    elements = AliveTable.scan()
    aliveNodes = []
    for element in elements['Items']:
        if int(element['lastTimeAlive']) >= nowInMilli - aliveInterval:
            aliveNodes.append(element['name'])
    aliveNodes.sort()
    return aliveNodes


def keyVNodeId(key):
    return xxhash.xxh64_intdigest(key) % 1024


def createURL(op, node, key, virtualKey, data=None, expiration_date=None):
    # return a url for each action
    if op == 'put':
        return f'http://{node}:8080/{op}_from_instance?virtualKey={virtualKey}&strKey={key}&data={data}&expiration_date={expiration_date}'
    if op == 'get':
        return f'http://{node}:8080/{op}_from_instance?strKey={key}&virtualKey={virtualKey}'


@app.route('/put', methods=['GET', 'POST'])
def put():
    key = request.args.get('strKey')
    data = request.args.get('data')
    expirationDate = request.args.get('expiration_date')
    nodes = getAllAliveInstances()
    virtualKey = keyVNodeId(key)
    index = jump.hash(int(virtualKey), len(nodes))
    node = nodes[index]
    altNode = nodes[(index + 1) % len(nodes)]
    try:
        if node == IpAddress:
            ans = json.loads(addToCache(key, data, virtualKey, expirationDate))
        else:
            ans = requests.post(createURL('put', altNode, key, virtualKey, data, expirationDate)).json()
        if altNode == IpAddress:
            json.loads(addToCache(key, data, virtualKey, expirationDate))
        else:
            requests.post(createURL('put', altNode, key, virtualKey, data, expirationDate)).json()
    except:
        return f'error occurred, item {key} was not added successfully', 404
    return ans, 200


@app.route('/put_from_instance', methods=['GET', 'POST'])
def putFromInstance():
    key = request.args.get('strKey')
    data = request.args.get('data')
    virtualKey = int(request.args.get('virtualKey'))
    expiration_date = request.args.get('expiration_date')
    return addToCache(key, data, virtualKey, expiration_date)


def addToCache(key, data, virtualKey, expiration_date):
    virtualNode = cache.get(virtualKey)
    if virtualNode is None:
        virtualNode = {}
    virtualNode[key] = (data, expiration_date)
    cache[virtualKey] = virtualNode
    return json.dumps({'key': key,
                       'item': cache[virtualKey][key],
                       'status': 'A new item was successfully added to cache'})


@app.route('/get', methods=['GET', 'POST'])
def get():
    key = request.args.get('strKey')
    nodes = getAllAliveInstances()
    virtualKey = keyVNodeId(key)
    index = jump.hash(int(virtualKey), len(nodes))
    node = nodes[index]
    altNode = nodes[(index + 1) % len(nodes)]
    try:
        ans = requests.get(createURL('get', node, key, virtualKey), timeout=8)
        if ans.status_code == 404:
            ans = requests.get(createURL('get', altNode, key, virtualKey), timeout=8)
    except Timeout:
        ans = requests.get(createURL('get', altNode, key, virtualKey), timeout=8)
    return ans.json(), ans.status_code


@app.route('/get_from_instance', methods=['GET', 'POST'])
def getFromInstance():
    key = request.args.get('strKey')
    virtualKey = int(request.args.get('virtualKey'))
    return cache[virtualKey][key][1]


if __name__ == '__main__':
    IpAddress = requests.get('https://api.ipify.org').text
    print('this node IP address: {}'.format(IpAddress))
    app.run(host='0.0.0.0', port=8080)
