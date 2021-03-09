#dependencies oscpy


from oscpy.server import OSCThreadServer
from oscpy.client import OSCClient
from functools import partial
import json
import signal
import argparse
import threading
import os
import time, datetime
import sys


parser = argparse.ArgumentParser(description='Command line tool for controlling totalmix from RME')
actionParser = parser.add_subparsers(title='actions')#add_mutually_exclusive_group(required=False)
# subParser = parser.add_subparsers(help='actions')

parser.add_argument('-i', '--interactive', action='count', help='run in interactive mode')
parser.add_argument('-f', '--fetch', action='count', default=0, help='fetch device layout and properties, use -ff for also fetching all channel sends (may take a while depending on channel count')
parser.add_argument('-F', '--file', default='tm-fetched.json', help='use prefetched values from file or fetch and write to file if -f')
parser.add_argument('-o', '--port', type=int,  default=2, help='either 1,2,3 or 4, default is 2 for second default osc-control (9002:localhost:7002')
parser.add_argument('-r', '--remote', help='<portTmOut>:<tm-ip>:<tmReceive>, e.g. 9002:192.168.178.27:7002 for local control for default osc-control 2'
                                           ' overwrites -o')
parser.add_argument('-v', '--verbose', action='count', help='verbosity level, no function yet')

# setParser = subParser.add_parser('--set', help='setvalues')
setParser = actionParser.add_parser('set', help='set parameter, "set -h" for help')
setParser.set_defaults(selectedAction='set')
setParser.add_argument('channel', action='store', help='channel to process starting with index 1, layer and channels are divided with  a ".", channelrange ":", different channels/-ranges ","e.g. "output.1:3,6,13:16", "playback.1,2,3,4,5", "input.5:10"')
setParser.add_argument('parameter', action='store', help='parameter to set')
setParser.add_argument('value', action='store', type=float, help='value to set to')
setParser.add_argument('-f', '--fast', action='store_true', help='"fast-mode":set values fast using the prefetchted data. Might not set correctly if changed parameters since fetch. NOT IMPLEMENTED YET')

copyParser = actionParser.add_parser('copy', help='copy a parameter from a channel, "copy -h" for help, NOT IMPLEMENTED YET')
copyParser.set_defaults(selectedAction='copy')
daemonParser = actionParser.add_parser('daemon', help='run as daemon, e.g. watch a channel for synchronising Eqs, NOT IMPLEMENTED YET')
copyParser.set_defaults(selectedAction='daemon')
# setParser.add_argument('parameter', help='parameter to set')
# setParser.add_argument('value', help='Value of paraemter')
# setParser.add_argument('channel', help='channel to perform action on starting with index 1, layer and channels are divided with ".", channelranges ":", different channels/-ranges ","e.g. "output.1:3,6,13:16", "playback.1,2,3,4,5", "input.5:10"')

# parseAction = subParser.add_parser('-a', help='perform action (copy is not implemented yet)')

#
# parseAction.add_argument('parameter', default='', help='parameter to set.')
# parseAction.add_argument('value', default=0, help='number value to set to 0 - 1 ')
# parseAction.add_argument('channel', default='', help='channel to perform action on starting with index 1, layer and channels are divided with ".", channelranges ":", different channels/-ranges ","e.g. "output.1:3,6,13:16", "playback.1,2,3,4,5", "input.5:10"')
# parser.add_argument('-a', '--action', default=None, choices=['set', 'copy'], help='perform action (copy is not implemented yet)')
# parser.add_argument('-p', '--parameter', default='', help='parameter to set.')
# parser.add_argument('-vf', '--value', type=float, default=0, help='number-value to set to from 0 to 1')
# parser.add_argument('-val' '--realvalue', default='', help='real vlaue e.g. "300hz" or "-6db"')
# parser.add_argument('-ch', '--channel', default='', help='channel to process starting with index 1, layer and channels are divided with  a ".", channelrange ":", different channels/-ranges ","e.g. "output.1:3,6,13:16", "playback.1,2,3,4,5", "input.5:10"')




args = parser.parse_args()


def oscR_receivedTmData(address, *args):
    sOsc = address.decode()
    if sOsc[0:2] == '/2':
        try:
            tmpChannelData[sOsc[3:]] = args[0].decode()
        except:
            tmpChannelData[sOsc[3:]] = args[0]

        if settingTargetValue:
            checkValue()
    # elif sOsc[0:2] == '/1':
    #     pass
    else:
        return


def oscR_setLayer(layer: str, mode: int, *args):

    if args[0] == 1.0:
        global currentLayer
        currentLayer = layer


def oscR_selectedSubmix(mode: int, *args):

    global selectedSubmixName, selectedSubmixIndex, changingChannel
    selectedSubmixName = args[0].decode()

    if channelPropertiesFetched:
        selectedSubmixIndex = channelNamesByIndex[output].index(selectedSubmixName)

    if mode == 2:
        checkTaskStack()
    elif mode == 1:
        global countFader
        if countFader:
            countFader = False


chLimitReached = False
checkChannelLimit = False
def oscR_setChannelName(*args):
    chName = args[0].decode()
    if checkChannelLimit:
        global chLimitReached, tmpChannelName
        chLimitReached = tmpChannelName == chName
    tmpChannelName = chName

numberFader = 0
countFader = True

def oscR_countRemoteFader(nFader, *args):
    global numberFader
    if countFader:
        numberFader = nFader
        if nFader > 1:
            sOSc = '/1/labelS{}'.format(nFader-1)
            oscServer.unbind(sOSc.encode(), partial(oscR_countRemoteFader, nFader-1))
    else:
        sOSc = '/1/labelS{}'.format(numberFader)
        oscServer.unbind(sOSc.encode(), partial(oscR_countRemoteFader, numberFader))


def oscR_tmpChannelDataMode1(fader:int, key:str, *args):

    try:
        value = args[0].decode()
    except:
        value = args[0]

    tmpChannelDataMode1[key][fader] = value

    if fader == 1 and key == 'name':
        tmpChannelName = value
        global currentChIndex
        if value in channelNamesByIndex:
            currentChIndex = channelNamesByIndex[currentLayer].index(value)


def oscR_dataMode1complete(*args):
    checkTaskStack()


def createChanVolDic(vol=0.0, pan=0.5) -> dict:
    return {
        'vol': vol,
        'pan': pan
    }


def checkTaskStack(*args):
    global timeout
    timeout.cancel()

    if taskStack:
        timeout = scheduleTimeOut(taskStack[0])
        timeout.start()
        taskStack.pop(0)()
    else:
        print('no tasks on stack')
        timeout = scheduleTimeOut()
        timeout.start()

    # try:
    #     # print(taskStack[0])
    #
    #     taskStack.pop(0)()
    # except:
    #     print('no tasks on stack')



def oscS_goToLayer(layer: str, mode: int = 2):
    initTmpData()
    sOsc = '/{}/{}'.format(mode, layer)
    toTM.send_message(sOsc.encode(), [1.0])


def oscS_goToChannelIndex(index: int):
    global currentChIndex
    currentChIndex = index
    toTM.send_message(b'/setBankStart', [float(index)])


def oscS_goToNextChannel():
    global currentChIndex
    if getDataOfSelectedChannel()['stereo'] == 1.0:
        currentChIndex = currentChIndex + 2
    else:
        currentChIndex = currentChIndex + 1

    toTM.send_message(b'/2/track+', [1.0])

def oscS_previousChannel(mode:int=2):
    if mode == 2:
        toTM.send_message(b'/2/track-', [1.0])
    else:
        toTM.send_message(b'/1/track+', [1.0])

def oscS_goToNextBank():
    toTM.send_message(b'/1/bank+', [1.0])

def oscS_previousBank():
    toTM.send_message(b'/1/bank-', [1.0])


def oscS_selectSubmix(outChannel:int):
    if not selectedSubmixIndex == outChannel:
        toTM.send_message(b'/setSubmix', [float(outChannel)])
        global timeout
        if timeout.is_alive():
            timeout.cancel()
        timeout = threading.Timer(0.5, checkTaskStack)
        timeout.start()
    else:
        checkTaskStack()


lastChName = None
def goToFirstChannel(mode:int=1):
    if tmpChannelName == lastChName:
        checkTaskStack()
    else:
        taskStack.insert(0, partial(goToFirstChannel, mode))
        oscS_previousBank()

def getDataOfSelectedChannel() -> dict:
    return channelDataByName[currentLayer][channelNamesByIndex[currentLayer][currentChIndex]]

def getChannelDataByIndex(layer:str, idx:int, key:str=''):
    if key:
        return channelDataByName[layer][channelNamesByIndex[layer][idx]][key]
    else:
        return channelDataByName[layer][channelNamesByIndex[idx]]


def fetchChannelProperties():

    global chLimitReached
    if chLimitReached:
        chLimitReached = False
        checkTaskStack()
    else:
        global tmpChannelData, checkChannelLimit
        channelNamesByIndex[currentLayer].append(tmpChannelName)
        if tmpChannelData['stereo'] == 1.0:
            channelNamesByIndex[currentLayer].append(tmpChannelName)
        channelDataByName[currentLayer][tmpChannelName] = tmpChannelData.copy()
        tmpChannelData = {}
        checkChannelLimit = True
        taskStack.insert(0, fetchChannelProperties)

        oscS_goToNextChannel()


def fetchChannelVolume():
    global tmpChannelDataMode1, channelSends, outputReceives, outputVolumes
    countedFader = numberFader
    for idx in range(len(tmpChannelDataMode1['name'].keys())):
        chName = tmpChannelDataMode1['name'][idx]
        if chName == 'n.a.':
            countedFader = idx
            break

        chIdx = channelNamesByIndex[currentLayer].index(chName)
        chDic = createChanVolDic(tmpChannelDataMode1['vol'][idx],
                                 tmpChannelDataMode1['pan'][idx])
        if currentLayer == output:
            chDic['name'] = chName
            chDic['index'] = chIdx
            outputVolumes[chIdx] = chDic
            outputVolumes[chName] = chDic
        else:
            outputIndex = selectedSubmixIndex
            if not chIdx in channelSends[currentLayer].keys():
                channelSends[currentLayer][chIdx] = {}
            if not outputIndex in outputReceives[currentLayer].keys():
                outputReceives[currentLayer][outputIndex] = {}
            channelSends[currentLayer][chIdx][selectedSubmixIndex] = chDic
            outputReceives[currentLayer][outputIndex][chIdx] = chDic

    lastChannelReached = bool(tmpChannelDataMode1['name'][countedFader-1] == channelNamesByIndex[currentLayer][-1])
    tmpChannelDataMode1 = initTmpChannelDataMode1()
    if lastChannelReached:
        # if currentLayer == output:
        #     checkTaskStack()
        #     return

        if channelNamesByIndex[output][selectedSubmixIndex + 1] == channelNamesByIndex[output][selectedSubmixIndex]:
            nextSubmixIdx = selectedSubmixIndex + 2
        else:
            nextSubmixIdx = selectedSubmixIndex + 1


        if nextSubmixIdx < numberTmChannels:
            taskStack.insert(0, fetchChannelVolume)
            taskStack.insert(0, partial(oscS_goToChannelIndex, 0))
            oscS_selectSubmix(nextSubmixIdx)
        else:
            checkTaskStack()

    else:
        taskStack.insert(0, fetchChannelVolume)
        oscS_goToNextBank()

def setPropertiesFetched(val:bool=True):
    global channelPropertiesFetched
    channelPropertiesFetched = val
    global numberTmChannels
    numberTmChannels = len(channelNamesByIndex[input])
    checkTaskStack()

def setVolumesFetched(val:bool=True):
    global channelVolumeFetched
    channelVolumeFetched = val
    checkTaskStack()

def startInit():

    if not shutdown:
        thingsToFetch = []
        if shallFetchProperties:
            print('fetch properties')
            thingsToFetch.append((fetchChannelProperties, 2))
        if shallFetchVolumes:
            print('fetch gains')
            thingsToFetch.append((fetchChannelVolume, 1))
        global currentLayer
        currentLayer = ''

        for fetch, mode in thingsToFetch:
            for layer in [output,input,playback]:
                print('setting up tasks', fetch, mode, layer)
                taskStack.append(partial(oscS_goToLayer, layer, mode))
                if mode == 1:
                    taskStack.append(partial(oscS_selectSubmix, 0))
                taskStack.append(partial(oscS_goToChannelIndex, 0))
                taskStack.append(fetch)
            if mode == 2:
                taskStack.append(setPropertiesFetched)
            elif mode == 1:
                taskStack.append(setVolumesFetched)

        # if not (shallFetchProperties and shallFetchVolumes)


        taskStack.append(finishInit)
        checkTaskStack()


shutdown = False
def finishInit():

    print('finished init')
    print('opentasks:', taskStack)

    if (shallFetchVolumes or shallFetchProperties) and args.file:
        # print('filename', args.file)
        fname = args.file
        with open(fname, 'w') as fp:
            completeDict = {
                fetchtime: time.time(),
                'channel properties': channelDataByName,
                'channel indices': channelNamesByIndex,
                'output volumes': outputVolumes,
                'channel sends': channelSends,
                'output receives': outputReceives
            }
            json.dump(completeDict, fp, indent=5)

        fp.close()
        print('results written to', fname)


    verifyTargetChannels()
    if targetParameter:
        _channelsToSet = set()
        for _ch in channelsToSet:
            _channelsToSet.add(_ch+1)
        print(' start setting parameter', targetParameter, targetValue, 'for channels', _channelsToSet, 'on layer', layerToSet)
    else:
        print('no parameter to set')

    # print('channelsss', channelsToSet)

    if channelsToSet:
        prepareSettingValues()
    else:
        exitProgram()


def setValueWithSubDicts(targetDict:dict, keylist:[], value):
    if len(keylist)>1:
        key = keylist.pop(0)
        subDict: dict
        if key in targetDict.keys():
            subDict = targetDict[key]
        else:
            subDict = {}
            targetDict[key] = subDict
        setValueWithSubDicts(subDict, keylist, value)

    else:
        # print('setVlaue tree', targetDict, keylist, value)
        targetDict[keylist.pop()] = value


def readPrefetchFile(fname:str) -> bool:
    everythingsFine = True
    global channelDataByName,channelNamesByIndex, outputVolumes, outputReceives, channelSends
    try:
        with open(fname) as dicF:
            data = json.load(dicF)
            print('using layout fetched at', datetime.datetime.fromtimestamp(data[fetchtime]))
            channelDataByName = data['channel properties']
            channelNamesByIndex = data['channel indices']
            _tmpOutputReceives = data['output receives']
            _tmpOutputVolumes = data['output volumes']
            # _tmpChannelSends = data['channel sends']


            for chName in channelDataByName[output].keys():

                idx = channelNamesByIndex[output].index(chName)
                if str(idx) in data['output volumes'].keys() and chName in data['output volumes'].keys():
                    outDic = data['output volumes'][chName]
                    outputVolumes[idx] = outDic
                    outputVolumes[chName] = outDic


            for _layer, _outChannels in _tmpOutputReceives.items():
                for _outCh, _sendChannels in _outChannels.items():
                    for _sendCh, _data in _sendChannels.items():
                        setValueWithSubDicts(outputReceives, [_layer, _outCh, _sendCh], _data)
                        setValueWithSubDicts(channelSends, [_layer, _sendCh, _outCh], _data)

            # fetchDict = {}
            # for _layer, _channels in channelNamesByIndex.items():
            #     fetchDict[_layer] = set()
            #     _pcName = ''
            #     for sChan, _cName in enumerate(_channels):
            #         if not _pcName == _cName:
            #             _pcName = _cName
            #             fetchDict[_layer].add(sChan)


            # for _layer in [input, playback]:
            #     outputReceives[_layer] = {}
            #     channelSends[_layer] = {}
            #     for _ch in fetchDict[_layer]:
            #         for _out in fetchDict[output]:
            #             print('bis ich hier komme ich', _ch, _out)
            #             print('das kann ich lesen', _tmpOutputReceives)
            #             _chDict = _tmpOutputReceives[str(_out)][str(_ch)]
            #             if not _ch in channelSends[_layer].keys():
            #                 channelSends[_layer][int(_ch)] = {}
            #             if not _ch in outputReceives[_layer].keys():
            #                 outputReceives[_layer][int(_ch)] = {}
            #             channelSends[_layer][int(_ch)][int(_out)] = _chDict
            #             outputReceives[_layer][int(_out)][int(_ch)] = _chDict

        dicF.close()



    except:
        print("Unexpected error:", sys.exc_info()[0])
        print('CAUTION no data file found, or data corrupted')
        everythingsFine = False

    if everythingsFine:
        global numberTmChannels
        numberTmChannels = len(channelNamesByIndex[input])

    return everythingsFine


def verifyTargetChannels():

    while (channelNameRanges):
        chRange = channelNameRanges.pop()
        if chRange == 'all':
            print('all channels', numberTmChannels)
            for c in range(numberTmChannels):
                channelsToSet.add(c)
        else:
            try:
                lowIdx = channelNamesByIndex[layerToSet].index(chRange[0])
                highIdx = channelNamesByIndex[layerToSet].index(chRange[1])

                for c in range(lowIdx, highIdx + 1):
                    channelsToSet.add(c)
            except:
                print('Channels', chRange, 'not found in TM Data and will not be set')

    _limitReached = False
    _channelsToRemove = set()
    _channelsToAdd = set()
    for c in channelsToSet:
        if c > 0 and c % 2:
            chSt = bool(getChannelDataByIndex(layerToSet, c, 'stereo'))
            if chSt:
                _channelsToRemove.add(c)
                _channelsToAdd.add(c - 1)

        if c >= numberTmChannels:
            _channelsToRemove.add(c)
            _limitReached = True
    for c in _channelsToRemove:
        channelsToSet.remove(c)
    for c in _channelsToAdd:
        channelsToSet.add(c)

    if _limitReached:
        print('channel limit is', numberTmChannels, 'higher channels will not be set')


def prepareSettingValues():


    taskStack.clear()
    taskStack.append(setValuesForTargetChannels)

    oscS_goToLayer(layerToSet)

# def startWorking():
#     doWhatYouMustDo.clear()
#     doWhatYouMustDo.append(doIt)
#     oscS_goToLayer()

settingTargetValue = False
def checkValue():
    global settingTargetValue
    if tmpChannelData[targetParameter] == targetValue:
        settingTargetValue = False
        setValuesForTargetChannels()
    else:
        settingTargetValue = True
        if parameterIsToggle:
            oscS_toggleValue(targetOsc)
        else:
            oscS_doSetValue(targetOsc, float(targetValue))


def oscS_doSetValue(oscAd, value):
    toTM.send_message(oscAd, [value])

def oscS_toggleValue(oscAd):
    toTM.send_message(oscAd, [1.0])


def setValuesForTargetChannels():
    if channelsToSet:
        c = channelsToSet.pop()
        taskStack.append(checkValue)
        oscS_goToChannelIndex(c)

    else:
        print('finished setting values')
        exitProgram()


def exitProgram():
    global shutdown
    if not shutdown:
        shutdown = True
        print('shutting down')
        threading.Timer(0.678, sshhhuh).start()


def sshhhuh():
    print('ssshshhhuuuu', os.getpid())
    timeout.cancel()
    # del timeout
    oscServer.close()
    # del oscServer
    os.kill(os.getpid(), signal.SIGQUIT)


def scheduleTimeOut(lastFunction=None, t=5):
    return threading.Timer(t, timeoutCalled, args=[lastFunction])


def timeoutCalled(lastFunctionCall=None):
    print('process timeout.\nTotalmix is not responding, configuration has failures or there is a bug.'
          '\nLast function called is', lastFunctionCall, '\nTasks on stack are', taskStack)
    exitProgram()


def dumdumdummyfunc():
    pass

timeout = scheduleTimeOut()

shallFetchProperties = True
channelPropertiesFetched = False
shallFetchVolumes = True
channelVolumeFetched = False

rcvPort = 9002
sendPort = 7002
sendAddress = 'localhost'

input = 'busInput'
playback = 'busPlayback'
output = 'busOutput'

changingLayer = False
changingChannel = False

currentLayer = ''
controlLayer = 0

currentChIndex = -1

selectedSubmixName = ''
selectedSubmixIndex = -1

tmpChannelData = {}
tmpChannelName = ''

def initTmpChannelDataMode1() -> dict:
    return {
    'vol': {},
    'pan': {},
    'name': {}
}

tmpChannelDataMode1 = initTmpChannelDataMode1()

def initTmpData():
    global tmpChannelDataMode1, tmpChannelData, tmpChannelName
    tmpChannelData = {}
    tmpChannelName = ''
    tmpChannelDataMode1 = initTmpChannelDataMode1()

channelNamesByIndex = {
    input: [],
    playback: [],
    output: []
}

channelDataByName = {
    input: {},
    playback: {},
    output: {}
}
numberTmChannels = 0

channelSends = {
    input: {},
    playback: {}
}
outputReceives = {
    input: {},
    playback: {}
}
outputVolumes = {}

taskStack = []


# parsing input

if args.interactive:
    print('I\'m so sorry. Interactive mode is not implemented yet. \nBe patient...')


fetchtime = 'fetchtime'
if args.fetch and args.fetch > 0:
    # shallFetchVolumes = True
    # shallFetchProperties = True
    shallFetchProperties = args.fetch > 0
    shallFetchVolumes = args.fetch > 1
else:
    print('dont fetch channel layout')
    shallFetchVolumes = False
    shallFetchProperties = False

    if args.file:
        readPrefetchFile(args.file)
        # try:
        #     with open(args.file) as dicF:
        #         data = json.load(dicF)
        #         print('using layout fetched at', datetime.datetime.fromtimestamp(data[fetchtime]))
        #         channelDataByName = data['channel properties']
        #         channelNamesByIndex = data['channel indices']
        #         outputVolumes = data['output volumes']
        #         outputReceives = data['output receives']
        #         channelSends = data['channel sends']
        #
        #     dicF.close()
        #
        # except:
        #     print('CAUTION no data file found')


if args.remote:
    remoteParams = args.remote.split(':')
    rcvPort = int(remoteParams[0])
    sendAddress = remoteParams[1]
    sendPort = remoteParams[2]
else:
    sendPort = 7000 + int(args.port)
    rcvPort = 9000 + int(args.port)


#INTIALISE
# startInit()
print('arguments are __', args)

selectedAction = ''
try:
    selectedAction = args.selectedAction
except:
    pass

if selectedAction == 'set':
    targetParameter = args.parameter
    targetValue = args.value
    targetChannels = args.channel
else:
    targetParameter = ''
    targetValue = None
    targetChannels = ''

targetOsc = '/2/{}'.format(targetParameter).encode()

parameterIsToggle = True


channelsToSet = set()
channelNameRanges = set()
layerToSet = ''
if targetChannels:
    channelArgs = targetChannels.split('.')
    _layer = channelArgs[0]
    # splitIdx = args.channel.find('.')
    # if splitIdx > 0:
    #     _layer = args.channel[]

    # print(args.channel)

    # try:
    #     splitIdx = args.channel.index('.')
    #     # print(splitIdx)
    #     _layer = args.channel[:splitIdx]
    # except:
    #     print('ERROR something wrong with layer selection')
    if _layer in ['input', 'output', 'playback']:

        _layerNames = {
            'input': input,
            'output': output,
            'playback': playback
        }
        layerToSet = _layerNames[_layer]
        if len(channelArgs) == 1 or channelArgs[0] in ['', 'all', ':'] \
                or (len(channelArgs)==2 and channelArgs[1]==''):
            channelNameRanges.add('all')

        else:
            _channelsRaw = channelArgs[1].split(',')

            _channelStrings = set()

            for _ch in _channelsRaw:
                try:
                    channelsToSet.add(int(_ch)-1)
                except:
                    _channelStrings.add(_ch)

            for _chStr in _channelStrings:

                try:
                    _chStr = _chStr.split(':')
                    # print('splitted', _chR)
                    try:
                        for c in range(int(_chStr[0]) - 1, int(_chStr[1])):
                            channelsToSet.add(c)
                    except:
                        if len(_chStr) == 2:
                            channelNameRanges.add((_chStr[0], _chStr[1]))
                        else:
                            print('something wrong with channel range', _chStr)
                except:
                    channelsToSet.add(_chStr)


    else:
        print('layer is missing in -ch', args.channel)





toTM = OSCClient(address=sendAddress, port=sendPort)

oscServer = OSCThreadServer(default_handler=oscR_receivedTmData)
oscServer.listen(address='0.0.0.0', port=rcvPort, default=True)

for i in [1, 2]:
    for bus in ['busInput', 'busPlayback', 'busOutput']:
        oscAddr = ('/'+str(i)+'/'+bus).encode()
        oscServer.bind(oscAddr, partial(oscR_setLayer, bus, i))

    sOsc = '/{}/labelSubmix'.format(i)
    oscServer.bind(sOsc.encode(), partial(oscR_selectedSubmix, i))
    del sOsc

oscServer.bind(b'/2/trackname', partial(oscR_setChannelName))


for i in range(64):
    sOSc = '/1/labelS{}'.format(i+1)
    oscServer.bind(sOSc.encode(), partial(oscR_countRemoteFader, i+1))
    sOSc = '/1/volume{}'.format(i+1)
    oscServer.bind(sOSc.encode(), partial(oscR_tmpChannelDataMode1, i, 'vol'))
    sOsc = '/1/pan{}'.format(i+1)
    oscServer.bind(sOsc.encode(), partial(oscR_tmpChannelDataMode1, i, 'pan'))
    sOsc = '/1/trackname{}'.format(i+1)
    oscServer.bind(sOsc.encode(), partial(oscR_tmpChannelDataMode1, i, 'name'))
    del sOsc

oscServer.bind(b'/1/micgain8', oscR_dataMode1complete)

if shutdown:
    print('shutting down... cause I got nothing to do.. or something went wrong')
    exitProgram()
else:
    startInit()
    signal.pause()
