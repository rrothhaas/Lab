#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Information on intan data formats: 
http://intantech.com/files/Intan_RHD2000_data_file_formats.pdf

--Channel Allocation for EEG, EMG, LFP
If you want to set a specific EEG channel as EEG.mat 
(and it's not the first 'e' in the allocation string), then use capital E, M, or L.
If all e's, m's, or l's are lower- or uppper-case, the first e,m,l will be used as primary
EEG, EMG, LFP
For example, emEm, will use the second EEG for EEG.mat, and will use the first EMG as EMG.mat

--Notes
For the notes (generated by the intan system), I assume the following syntax:
Notes start with the following string:
#Notes:
(followed by newline)
Individual notes start with //
To designate a note to a specific mouse use '@MOUSE_ID'.
For example, the note
//@S10 sleeping well today
will be assigned to mouse S10. But the note
//lights problems today
will go to all recorded mice 

DATE 03/08/18:
    loading digital input (and saving it) as uint16 (instead of int16)

DATE 04/04/18:
    added 'port' as new info field
    extended preallocated dictionary for translation digital input to int array to include 2^16 keys

DATE 4/13/18:
    added closed vs open loop processing of digital inputs

DATE 5/29/18:
    added function intan_video_timing to explicitely save timing of video frames into file
    video_timing.mat

DATE 10/21/18:
    copying timestamps to recordings directories and mkv video

DATE 04/17/19:
    reading the conversion factor from parameter file, if present in there.

DATE 05/01/19:
    upgraded to py3

DATE 01/25/2020:
    strobe signal from camera 1 and camera 2 are separately processed:
    Signal from cam1 goes to digital input 2, signal from cam2 goes to digital input 11

@author: Franz and Justin
"""
import tkinter as Tk
import tkinter.filedialog as tkf
import sys
import re
import os.path
import numpy as np
import scipy.io as so
from shutil import copy2, move
from functools import reduce

import pdb
# to do: copy video file, process video file, time.dat
# Channel allocation


def get_snr(ppath, name):
    """
    read and return SR from file $ppath/$name/info.txt 
    """
    fid = open(os.path.join(ppath, name, 'info.txt'), newline=None)
    lines = fid.readlines()
    fid.close()
    values = []
    for l in lines :
        a = re.search("^" + 'SR' + ":" + "\s+(.*)", l)
        if a :
            values.append(a.group(1))            
    return float(values[0])


def laser_start_end(laser, SR=1525.88, intval=5):
    """laser_start_end(ppath, name) ...
    print start and end index of laser stimulation trains: For example,
    if you was stimulated for 2min every 20 min with 20 Hz, return the
    start and end index of the each 2min stimulation period (train)

    returns the tuple (istart, iend), both indices are inclusive,
    i.e. part of the sequence
    @Param:
    laser    -    laser, vector of 0s and 1s
    intval   -    minimum time separation [s] between two laser trains
    @Return:
    (istart, iend) - tuple of two np.arrays with laser start and end indices
    """
    idx = np.where(laser > 0.5)[0]
    if len(idx) == 0 :
        #return (None, None)
        return ([], [])
    
    idx2 = np.nonzero(np.diff(idx)*(1./SR) > intval)[0]
    istart = np.hstack([idx[0], idx[idx2+1]])
    iend   = np.hstack([idx[idx2], idx[-1]])    

    return (istart, iend)



def get_infoparam(ppath, name):
    """
    name is a parameter/info text file, saving parameter values using the following
    syntax:
    field:   value 
    
    in regular expression:
    [\D\d]+:\s+.+    
    
    The function return the value for the given string field
    """
    fid = open(os.path.join(ppath, name), newline=None)    
    lines = fid.readlines()
    params = {}
    in_note = False
    fid.close()
    for l in lines :
        if re.search("^#[nN]otes:(.*)", l):
            #a = re.search("^#\s*(.*)", l)
            #params['note'] = [a.group(1)]
            #continue
            in_note = True
            params['note'] = []
            continue
        if in_note == True:
            if re.match("^[A-z_]+:", l):
                in_note=False
             
            if in_note and not(re.search("^\s+$", l)):
                params['note'].append(l)
        if re.search("^\s+$", l):
            continue
        if re.search("^[A-z_]+:" ,l):
            a = re.search("^(.+):" + "\s+(.*$)", l)
            if a :
                v = a.group(2).rstrip()
                v = re.split('\s+', v)
                params[a.group(1)] = v    
      
    # further process 'note' entry
    tmp = [i.strip() for i in params['note']]
    tmp = [i + ' ' for i in tmp]    
    if len(tmp)>0:
        f = lambda x,y: x+y
        tmp = reduce(f, tmp)
        tmp = re.split('//', tmp)
        tmp = ['#'+i for i in tmp if len(i)>0]

    #tmp = os.linesep.join(tmp)    
    params['note'] = assign_notes(params, tmp)
            
    return params


def assign_notes(params, notes):
    """
    check for each comment whether it was assigned to a specific mouse/mice using the 
    @ special sign; or (if not) assign it to all mice
    """
    comment = {} 
    
    mice = params['mouse_ID']
    for m in mice:
        comment[m] = []
    
    #notes = params['note']
    for l in notes:
        if re.match('@', l):
            for m in mice:
                if re.match('@' + m, l):
                    comment[m].append(l)
        else:
            comment[m].append(l)
                            
    #params['note'] = comment
    return comment


def file_time(filename):
    """
    get time stamp of file; 
    @RETURN:
        string of the format month+day+year, month, day and year each allocated 
        only two chars
    """
    import datetime
    t = os.path.getmtime(filename)
    d = datetime.datetime.fromtimestamp(t)
    day = str(d.day)
    month = str(d.month)
    year = str(d.year)
    
    if len(day) < 2:
        day = '0' + day
    if len(month) < 2:
        month = '0' + month
    year = year[2:]
        
    return month+day+year
    


def get_param_file(ppath):
    """
    get the parameter file, i.e. the only .txt file within the specified
    folder $ppath
    """
    
    files = [f for f in os.listdir(ppath) if re.search('\.txt$', f)]
    if len(files)>1:
        print("Error more than one .txt files in specified folder %s" % ppath)
        sys.exit(1)
    if len(files) == 0:
        print("Error no parameter file in specified folder %s" % ppath)
    else:
        return files[0]
    


def get_lowest_filenum(path, fname_base):
    """
    I assume that path contains files/folders with the name fname_base\d+
    find the file/folder with the highest number i at the end and then 
    return the filename fname_base(i+1)
    """
    files = [f for f in os.listdir(path) if re.match(fname_base, f)]
    l = []
    for f in files :
        a = re.search('^' + fname_base + "(\d+)", f)
        if a :
            l.append(int(a.group(1)))           
    if l: 
        n = max(l) + 1
    else:
        n = 1

    return fname_base+str(n)    



def parse_challoc(ch_alloc):
    """
    the channel allocation string must have one capital E,M,L (if present).
    If there are only lower-case e's, m's, or l's or only capital E's, M's, or L's,
    set the first e,m,l to upper-case and the rest to lower-case
    """
    
    # search for e's
    neeg = len(re.findall('[eE]', ch_alloc))
    nemg = len(re.findall('[mM]', ch_alloc))
    nlfp = len(re.findall('[lL]', ch_alloc))
    
    # only small e's
    if neeg == len(re.findall('e', ch_alloc)):
        ch_alloc = re.sub('e', 'E', ch_alloc, count=1)
    # only large E
    if neeg == len(re.findall('E', ch_alloc)):
        ch_alloc = re.sub('E', 'e', ch_alloc)
        ch_alloc = re.sub('e', 'E', ch_alloc, count=1)
    
    # only small m's
    if nemg == len(re.findall('m', ch_alloc)):
        ch_alloc = re.sub('m', 'M', ch_alloc, count=1)
    # only large M
    if nemg == len(re.findall('M', ch_alloc)):
        ch_alloc = re.sub('M', 'm', ch_alloc)
        ch_alloc = re.sub('m', 'M', ch_alloc, count=1)

    # only small l's
    if nlfp == len(re.findall('l', ch_alloc)):
        ch_alloc = re.sub('l', 'L', ch_alloc, count=1)
    # only large L
    if nlfp == len(re.findall('L', ch_alloc)):
        ch_alloc = re.sub('L', 'l', ch_alloc)
        ch_alloc = re.sub('l', 'L', ch_alloc, count=1)

    return ch_alloc



def intan_video_timing(ppath, rec, tscale=0):
    """
    creates .mat file video_timing.mat which contains
    two variables:
    onset       -     the onset of each video frame as decoded from the cameras strobing signal
    tick_onset  -     defines a time scale along which behaviors/frames are annotated
    tscale      -     if tscale==0, the annotation time scale is the same as the timing
                      of the video frames; otherwise specified in s.
    """
    sr = get_snr(ppath, rec)
    vfile = os.path.join(ppath, rec, 'videotime_' + rec + '.mat')
    vid = so.loadmat(vfile, squeeze_me=True)['video']

    # transform signal such that is movie frame onset
    # corresponds to a flip from 0 to 1
    vid = (vid - 1.0)*-1.0
    vid = vid.astype('int')
    len_rec = vid.shape[0]

    idxs,_ = laser_start_end(vid, SR=sr, intval=0.01)
    onset = idxs * (1.0/sr)
    tend = int(len_rec / sr)
    if tscale == 0:
        tick_onset = onset.copy()
    else:
        tick_onset = np.arange(0, tend, tscale)
    so.savemat(os.path.join(ppath, rec, 'video_timing.mat'), {'onset':onset, 'tick_onset':tick_onset})



#######################################################################################  
### START OF SCRIPT ###################################################################
#######################################################################################
# Parameters to set at each computer:
PPATH = '/Users/tortugar/Documents/Penn/Data/RawData'
ndig = 16
# To convert to electrode voltage in microvolts, multiply by 0.195
FACTOR = 0.195

# chose directory with intan raw files to be processed:
root = Tk.Tk()
intan_dir = tkf.askdirectory()
root.update()
# load all parameters from *.txt file, located in intan recording dir
param_file = get_param_file(intan_dir)

params = get_infoparam(intan_dir, param_file)
params['port'] = ['A', 'B', 'C', 'D']
mice = params['mouse_ID']
print("We have here the following mice: %s" % (' '.join(mice)))
# 4/17/19 inserted the following 5 lines:
if 'conversion' in params:
    FACTOR = float(params['conversion'][0])
    print("Found conversion factor: %f" % FACTOR)
else:
    params['conversion'] = [str(FACTOR)]

# total number of recorded channels
ntotal_channels = sum([len(a) for a in params['ch_alloc']])
print('In total, %d channels were used' % ntotal_channels)
# get time stamp of recording
if 'date' in params:
    date = params['date'][0]  
    dtag = re.sub('/', '', date)
else:
    dtag = file_time(os.path.join(intan_dir, 'amplifier.dat'))
print("Using %s as date tag" % dtag)

# load all data
print("Reading data file...")
data_amp = np.fromfile(os.path.join(intan_dir, 'amplifier.dat'), 'int16')
data_amp = data_amp * FACTOR
print("Processing digital inputs...")
data_din = np.fromfile(os.path.join(intan_dir, 'digitalin.dat'), 'uint16')
#pdb.set_trace()
# convert data_in to Array which each column corresponding to one digital input
#Din = np.fliplr(np.array([np.array(list(np.binary_repr(x, width=16))).astype('int16') for x in data_din]))
SR = int(params['SR'][0])
Din = np.zeros((data_din.shape[0], 16), dtype='uint16')
ihour = 0
nhour = data_din.shape[0] / (3600 * SR)

dinmap = {}
for i in range(0, 2**ndig):
    dinmap[i] = np.array(list(np.binary_repr(i, width=ndig)[::-1])).astype('uint16')

for j in range(data_din.shape[0]):
    if int(((j+1) % (3600*SR))) == 0:
        ihour += 1
        print("Done with %d out of %d hours" % (ihour, nhour))
    Din[j,:ndig] = dinmap[data_din[j]]


# consistency test: Number of data points in Din should match with data_amp:
if Din.shape[0] != data_amp.shape[0]/ntotal_channels:
    sys.exit('Something wrong: most likely some error in the channel allocation')

recording_list = []
# save data to individual mouse folders
imouse = 0
first_cl = 3
ch_offset = 0 # channel offset; 
for mouse in mice:
    print("Processing Mouse %s" % mouse)
    ch_alloc = parse_challoc(params['ch_alloc'][imouse])
    nchannels = len(ch_alloc)
    fbase_name = mouse + '_' + dtag + 'n' 
    name = get_lowest_filenum(PPATH, fbase_name)
    recording_list.append(name)
    
    if not(os.path.isdir(os.path.join(PPATH,name))):
        print("Creating directory %s\n" % name)
        os.mkdir(os.path.join(PPATH,name))        
    
    neeg = 1
    nemg = 1
    nlfp = 1
     # channel offset
    for c in ch_alloc:
        dfile = ''
        if re.match('E', c):
            dfile = 'EEG'
        if re.match('e', c):
            dfile = 'EEG' + str(neeg+1)
            neeg += 1
        if re.match('M', c):
            dfile = 'EMG'
        if re.match('m', c):
            dfile = 'EMG' + str(nemg+1)
            nemg += 1
        if re.match('L', c):
            dfile = 'LFP'
        if re.match('l', c):
            dfile = 'LFP' + (str(nlfp+1))
            nlfp += 1
        
        # Save EEG EMG
        if len(dfile) > 0:
            print("Saving %s of mouse %s" % (dfile, mouse))
            so.savemat(os.path.join(PPATH, name, dfile + '.mat'), {dfile: data_amp[ch_offset::ntotal_channels]})
        ch_offset += 1 # channel offset
        
    # save Laser
    if params['mode'][0] == 'ol':
        so.savemat(os.path.join(PPATH, name, 'laser_' + name + '.mat'), {'laser':Din[:,1]})
    elif params['mode'][0] == 'cl':
        so.savemat(os.path.join(PPATH, name, 'laser_' + name + '.mat'), {'laser': Din[:, first_cl]})
        so.savemat(os.path.join(PPATH, name, 'rem_trig_' + name + '.mat'), {'rem_trig': Din[:, first_cl + 4]})
        if 'X' not in name:
            first_cl += 1

    # save Video signals
    # NOTE: 01/25/2020: Distinguising between port 2 and 11 for camera signals
    # from box1 and box2
    # copy timestamp file #####################################################################################
    if imouse < 2:
        so.savemat(os.path.join(PPATH, name, 'videotime_' + name + '.mat'), {'video':Din[:,2]})
        tfiles = [f for f in os.listdir(intan_dir) if re.match('^timestamp\d', f)]
        if 'timestamp1.mat' in tfiles:
            copy2(os.path.join(intan_dir, 'timestamp1.mat'), os.path.join(PPATH, name, 'timestamp_%s.mat' % name))
    else:
        so.savemat(os.path.join(PPATH, name, 'videotime_' + name + '.mat'), {'video':Din[:,11]})
        tfiles = [f for f in os.listdir(intan_dir) if re.match('^timestamp\d', f)]
        if 'timestamp2.mat' in tfiles:
            copy2(os.path.join(intan_dir, 'timestamp2.mat'), os.path.join(PPATH, name, 'timestamp_%s.mat' % name))

    camfile = '%s_cam_%d.mkv' % (mouse, imouse+1)
    if os.path.isfile(os.path.join(intan_dir, camfile)):
        move(os.path.join(intan_dir, camfile), os.path.join(PPATH, name, 'video_' + name + '.mkv'))

    ###########################################################################################################

    # save on/off signal (signal indicate when the recording started and ended)
    # only save first and last index, when signal is on
    onoff = np.where(Din[:,0]>0.1)[0][[0,-1]]
    so.savemat(os.path.join(PPATH, name, 'onoff_' + name + '.mat'), {'onoff':onoff})
    
    # save info file - I do this to split the parameter.txt file into
    # individual info.txt files for each recorded mouse
    fid = open(os.path.join(PPATH, name, 'info.txt'), 'w')    
    # first write notes
    comments = params['note'][mouse]
    for l in comments:
        fid.write(l + os.linesep)
    # write all other info tags
    for k in list(params.keys()):
        v = params[k]
        if k == 'note':
            continue
        if len(v) == 1:
            # shared attribute
            fid.write(k + ':' + '\t' + v[0] + '\n')
        else:
            # individual attribute
            fid.write(k + ':' + '\t' + v[imouse] + '\n')
    # add a colleagues tag, i.e. other mice recorded together with mouse
    colleagues = mice[:]
    colleagues.remove(mouse)
    fid.write('colleagues:\t' + ' '.join(colleagues) + os.linesep)
    # 4/17/19 took this one out
    #fid.write('conversion:\t%.3f' % (FACTOR))
    fid.close()

    # copy info.rhd from intan_dir to PPATH/name
    copy2(os.path.join(intan_dir, 'info.rhd'), os.path.join(PPATH, name))
    
    # copy time.dat file
    copy2(os.path.join(intan_dir, 'time.dat'), os.path.join(PPATH, name))
        
    # end of loop over mice
    imouse += 1
    



