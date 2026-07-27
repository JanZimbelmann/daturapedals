from pythonosc.udp_client import SimpleUDPClient
import json
import os
import re
import math
import time
from time import sleep
import csv
import board
import busio
import digitalio
import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn
import subprocess
import time
import socket
import signal
from IPython.display import clear_output


DIRECTORY = os.path.dirname(os.path.abspath(__file__))

def setup_shutdown(processes):
    def shutdown(signum, frame):
        for p in reversed(processes):
            p.kill()  # SIGKILL, instant
        exit(0)
    
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    return shutdown

def start_jackd(hw=0):
    subprocess.run(["pkill", "-x", "jackd"], capture_output=True)
    for _ in range(20):
        result = subprocess.run(["pgrep", "-x", "jackd"], capture_output=True)
        if result.returncode != 0:
            break
        time.sleep(0.1)

    jack = subprocess.Popen(
        ["/usr/bin/jackd", "-R", "-P", "95", "-d", "alsa", "-d", "hw:"+str(hw), "-p", "512", "-n", "2"],
        stderr=subprocess.PIPE
    )

    time.sleep(3)  # just wait for it to start

    if jack.poll() is not None:
        # process already exited = failed
        print("jackd failed to start")
        raise RuntimeError("jackd failed")

    print("jackd is ready!")
    return jack



def wait_for_scsynth(host="127.0.0.1", port=57110, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            # send a /status OSC message
            sock.sendto(b"/status\x00", (host, port))
            sock.recvfrom(1024)
            sock.close()
            return True
        except:
            time.sleep(0.1)
    return False

def start_supercollider():
    sc = subprocess.Popen(
        ["scsynth", "-u", "57110", "-a", "1064", "-i", "2", "-o", "2",
        "-b", "4096", "-z", "128", "-m", "65536", "-w", "4096",
        "-V", "-1", "-R", "0", "-C", "1", "-l", "1"],
    )

    if wait_for_scsynth():
        print("scsynth is ready!")
    else:
        raise RuntimeError("scsynth failed to start")

    r1 = subprocess.run(["jack_connect", "SuperCollider:out_1", "system:playback_1"])
    r2 = subprocess.run(["jack_connect", "SuperCollider:out_2", "system:playback_2"])
    r3 = subprocess.run(["jack_connect", "system:capture_1", "SuperCollider:in_1"])
    r4 = subprocess.run(["jack_connect", "system:capture_2", "SuperCollider:in_2"])

    if any(r.returncode != 0 for r in [r1, r2, r3, r4]):
        raise RuntimeError("jack_connect failed")
    
    print("supercollider connected!")
    return sc

def restore_alsa_state(path=None):
    if path is None:
        path = os.path.join(os.path.expanduser("~"), "asound.state")
    result = subprocess.run(
        ["alsactl", "restore", "-f", path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"alsactl restore failed: {result.stderr.strip()}")
    else:
        print("ALSA state restored")

def start_internet():
    print("start internet") 
    subprocess.Popen(
        ["bash", os.path.join(os.path.expanduser("~"), "internet.sh")],
        # ["bash", os.path.join(DIRECTORY, "internet.sh")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    print("internet.sh triggered")

def sc_round(value, quant):
    return round(value / quant) * quant

def sc_wrap(n, low=1000, high=9999):
    span = high - low + 1
    return (n - low) % span + low

def load_jsons(dict_full, path, check_parent = True):
    ending = ".json"
    dict_return = {}
    if(check_parent):
        base = os.path.join(DIRECTORY, "..", "stores")
    else:
        base = path
    

    for folder in os.listdir(base):
        folder_path = os.path.join(base, folder)
        if os.path.isdir(folder_path):
            files = os.listdir(folder_path)
            files.sort(key=lambda x: x != 'info.json')    
            for file in files:
                if file.endswith(ending):
                    name = file.replace(ending, "")
                    final_path = os.path.join(folder_path, file)
                    with open(final_path) as f:
                        json_load = json.load(f)
                    if(name == "info"):
                        if(json_load["info"]["compatibility"] > dict_full["initialization"]["compatibility"]):
                            break
                    dict_return.setdefault(folder, {})
                    dict_return[folder][name] = json_load
    return dict_return

def load_folder_metadata(path, check_parent = True):
    ending = ".txarcmeta"
    dict_return = {}
    if(check_parent):
        base = os.path.join(DIRECTORY, "..", "stores")
    else:
        base = path
    for folder in os.listdir(base):
        folder_path = os.path.join(base, folder)
        if os.path.isdir(folder_path):
            for file in os.listdir(folder_path):
                if file.endswith(ending):
                    name = file.replace(ending, "")
                    final_path = os.path.join(folder_path, file)
                    with open(final_path) as f:
                        sc_text = f.read()
                    dict_return[name] = parse_sc_archive(sc_text)
    return dict_return


def load_scsyndef_paths(path, check_parent = True):
    ending = ".scsyndef"
    array_return = []
    if(check_parent):
        base = os.path.join(DIRECTORY, "..", "stores")
    else:
        base = path
    for folder in os.listdir(base):
        folder_path = os.path.join(base, folder)
        if os.path.isdir(folder_path):
            for file in os.listdir(folder_path):
                if file.endswith(ending):
                    name = file.replace(ending, "")
                    final_path = os.path.join(folder_path, file)
                    array_return.append(os.path.abspath(final_path))
    return array_return

"""
def load_scsyndef_paths(path, check_parent = True):
    if(check_parent):
        base = os.path.join(DIRECTORY, "..", path)
    else:
        base = path
    
    array_return = []
    for file in os.listdir(base):
        store_path = os.path.join(base, file)
        if(".scsyndef" in store_path):
            #array_return.append(store_path)
            array_return.append(os.path.abspath(store_path))
    return array_return
"""

def extract_blocks(text, type_name):
    pattern = re.finditer(rf'//\s*{type_name}\s*\n\s*(\d+),\s*\[', text)
    
    for m in pattern:
        idx = m.group(1)

        start = m.end()
        depth = 1
        i = start

        while i < len(text) and depth > 0:
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
            i += 1

        content = text[start:i-1]
        yield idx, content

def parse_sc_archive(text):
    warp_lookup = {}
    for warp_type in ["ExponentialWarp", "LinearWarp", "CurveWarp"]:
        for idx, content in extract_blocks(text, warp_type):

            if warp_type == "ExponentialWarp":
                warp_lookup[idx] = "exp"

            elif warp_type == "LinearWarp":
                warp_lookup[idx] = 0.0

            elif warp_type == "CurveWarp":
                m = re.search(r'curve:\s*([\d.e-]+)', content)
                warp_lookup[idx] = float(m.group(1)) if m else "curve"
    name_to_idx = {}

    for m in re.finditer(r"'([\w_]+)',\s*o\[(\d+)\]", text):
        name_to_idx[m.group(1)] = m.group(2)
    specs_by_idx = {}

    for idx, content in extract_blocks(text, "ControlSpec"):

        def get_float(key):
            m = re.search(rf'{key}:\s*([\d.e-]+)', content)
            return float(m.group(1)) if m else None

        def get_ref(key):
            m = re.search(rf'{key}:\s*o\[(\d+)\]', content)
            return m.group(1) if m else None

        specs_by_idx[idx] = {
            "min": get_float("minval"),
            "max": get_float("maxval"),
            "step": get_float("step"),
            "default": get_float("default"),
            "warp_idx": get_ref("warp"),
        }
    result = {}

    for name, idx in name_to_idx.items():
        spec = specs_by_idx.get(idx)
        if not spec:
            continue

        warp_idx = spec["warp_idx"]
        warp_val = warp_lookup.get(warp_idx, "unknown")

        result[name[:-5]] = {
            "min": spec["min"],
            "max": spec["max"],
            "step": spec["step"],
            "default": spec["default"],
            "warp": warp_val,
            "name": name
        }

    return result

"""
def load_folder_metadata(path, check_parent = True):
    dict_return = {}
    if(check_parent):
        base = os.path.join(DIRECTORY, "..", path)
    else:
        base = path
    
    for file in os.listdir(base):
        store_path = os.path.join(base, file)
        if(".txarcmeta" in store_path):
            with open(store_path) as f:
                sc_text = f.read()

            dict_return[file[:-10]] = parse_sc_archive(sc_text)

            #for name, s in dict_return[file].items():
            #    print(f"{name:20} | min: {s['min']:<10} | max: {s['max']:<10} | warp: {s['warp']:<5} | default: {s['default']:<11}|")
    return dict_return
"""


def read_csv_as_list(path = "pedalinputs.csv"):
    path = os.path.join(DIRECTORY, path)
    with open(path) as f:
        reader = csv.reader(f)
        data = [float(row[0]) for row in reader if row]
    return data

def read_pedal_inputs(dict_full, idx, from_csv):
    if(from_csv):
        try:
            data = read_csv_as_list("pedalinputs.csv")
            val = data[int(idx)]
        except Exception:
            print("Exception:", idx, data)
            time.sleep(0.1)
            print("Exception:", idx, data)
            data = read_csv_as_list("pedalinputs.csv")
            val = data[int(idx)]
    else:
        pedal_obj = dict_full["gpio"]["obj"][str(idx)]["in"]
        if(isinstance(pedal_obj, AnalogIn)):
            val = pedal_obj.voltage/3.3
        else:
            val = pedal_obj.value
        if(dict_full["gpio"]["obj"][str(idx)]["reverse"]):
            val = 1-val
    return val




def construct_orderings(dict_full):
    dict_full["info"]["next_orderings_synth"] = {d["info"]["info"]["ordering"]:k for k, d in dict_full["jsons"].items() if ((d["info"]["info"]["line"] == "synth") and (d["info"]["info"]["edition"] == dict_full["info"]["next_edition"]))}
    dict_full["info"]["next_orderings_fx"] = {d["info"]["info"]["ordering"]:k for k, d in dict_full["jsons"].items() if ((d["info"]["info"]["line"] == "fx") and (d["info"]["info"]["edition"] == dict_full["info"]["next_edition"]))}


def load_info(dict_full):
    dict_return = {
        "loop_prgrm": "play", 
        "pedal_obj_n": sum(1 for k in list(dict_full["jsons"].values())[0]["0"].keys() if k.isnumeric()),
        "troopers_id": 1000,
        "toggle": "toggle",
        "momentary_checking": True,
        "bpm_time": 0,
        "prgrm_time": 0,
        "bpm": 110,
        "sr": 48000,
        "editions": sorted({d["info"]["info"]["edition"] for d in dict_full["jsons"].values() if d["info"]["info"]["edition"] != "0"}, key = lambda k: int(k)),
        "morse_pause": (" "*4),
        "sleep": dict_full["initialization"]["sleep"]
        }
    

    jsons = dict_full["jsons"]
    dict_init = dict_full["initialization"]

    if ((dict_init["load_prgrm"]) and (dict_init["prgrm"] in jsons)):
        first_program = dict_full["initialization"]["prgrm"]
    else:
        first_program = min((k for k, v in jsons.items() if int(v.get("info", {}).get("info", {}).get("edition", 0)) != 0), key=lambda k: (int(jsons[k]["info"]["info"]["edition"]), jsons[k]["info"]["info"]["ordering"]))

    dict_return["prgrm"] = first_program
    dict_return["edition"] = jsons[first_program]["info"]["info"]["edition"]
    dict_return["ordering"] = jsons[first_program]["info"]["info"]["ordering"]

    dict_return["next_prgrm"] = dict_return["prgrm"]
    dict_return["next_edition"] = dict_return["edition"]
    dict_return["next_ordering"] = dict_return["ordering"]

    #remember_vals = [dict_full["obj_vals"][str(i)] for i in range(pedal_obj_n)]

    dict_return["remember_vals"] = [0] * dict_return["pedal_obj_n"]
    dict_return["len"] = sc_round(60/4/dict_return["bpm"], 1/dict_return["sr"])
    dict_return["time_diff"] = 60/dict_return["bpm"]

    return dict_return

def send_load_syndef(dict_full):
    for path in dict_full["syndef_paths"]:
        print("load", path)
        dict_full["client"].send_message(
            "/d_load",
            path
        )

def load_buffers(dict_full):
    dict_return = {}
    dict_return["empty"] = []
    buf_num = 0
    for i in range(5):
        dict_return["empty"].append(buf_num)
        dict_full["client"].send_message(
            "/b_alloc",
            [buf_num, dict_full["info"]["sr"] * 20, 2]
        )
        buf_num = buf_num + 1   
    return dict_return

def reset_buffers(dict_full):
    for buf_num in dict_full["buffers"]["empty"]:
        dict_full["client"].send_message("/b_zero", [buf_num])

def spec_map(val, dict_spec):
    minn = dict_spec["min"]
    maxx = dict_spec["max"]
    warp = dict_spec["warp"]
    step = dict_spec.get("step", 0)
    if warp=="exp":
        value = minn * ((maxx/minn)**val)
    elif warp == 0:
        value = minn + ((maxx - minn) * val)
    else:
        value = minn + ((maxx-minn) * ((1-math.exp(val*warp)) / (1-math.exp(warp)))) 
    
    if step != 0:
        value = round((value - minn) / step) * step + minn
        value = max(minn, min(maxx, value))  # re-clip after quantizing

    return value

def spec_unmap(val, dict_spec):
    minn = dict_spec["min"]
    maxx = dict_spec["max"]
    warp = dict_spec["warp"]
    if warp != "exp":
        if warp == 0:
            return (val - minn) / (maxx - minn)
        ratio = (val - minn) / (maxx - minn)
        return math.log(1 - ratio * (1 - math.exp(warp))) / warp      
    else:
        return math.log(val / minn) / math.log(maxx / minn)



def as_pairs(args_dict_synth):
    return [item for pair in args_dict_synth.items() for item in pair]

def as_pairs_puton(dict_full, sy_key):
    args_dict_sy = dict_full["args_dict"][sy_key]
    specs = dict_full["meta"][sy_key]
    return [specs[i]["name"] if type(i) == str and i in specs else i for p in args_dict_sy.items() for i in p]

def boundary_markers(markers, val100):
    array_return = []
    keys = sorted(int(k) for k in markers.keys())

    lower_keys = [k for k in keys if k <= val100]
    upper_keys = [k for k in keys if k >= val100]

    lower = max(lower_keys) if lower_keys else None
    upper = min(upper_keys) if upper_keys else None

    if(lower != None):
        array_return.append(str(lower))
    if(upper != None):
        array_return.append(str(upper))
    if(len(array_return)==1):
        array_return = array_return * 2

    return array_return

def linlin(val, in_min, in_max, out_min, out_max):
    if(in_min == in_max):
        return out_min
    return (val - in_min) / (in_max - in_min) * (out_max - out_min) + out_min

def update_args_dict(dict_full):
    dict_full["args_dict"] = {}
    json_to_load = dict_full["info"]["json_to_load"]
    prgrm = dict_full["info"]["prgrm"]
    for sy_key in dict_full["info"]["synth_order"]:
        dict_full["args_dict"][sy_key] = {"out": dict_full["jsons"][prgrm]["info"]["synths"][sy_key]["out"]}
    
    for obj_key, val in dict_full['obj_vals'].items():
        send_obj_fun(dict_full, obj_key, val, False)

def save_when_necessary(dict_full, excludes = []):
    prgrm = dict_full["info"]["prgrm"]
    dict_init = dict_full["initialization"]
    if((prgrm not in excludes) and dict_init["save_prgrm"]):
        dict_init["prgrm"] = prgrm
        with open(os.path.join(DIRECTORY, "initialization.json"), "w", encoding="utf-8") as f:
           json.dump(dict_init, f, indent=4)

def start_when_necessary(dict_full, next_prgrm, necessary = False, press_all = True):
    dict_info = dict_full["info"]
    if((next_prgrm != dict_info["prgrm"]) or necessary):
        #close previous
        send_obj_fun(dict_full, "closedown", 0, True)

        #dict_full["info"]["prgrm"]    = dict_full["info"]["next_prgrm"]
        #dict_full["info"]["ordering"] = dict_full["info"]["next_ordering"]
        #dict_full["info"]["edition"] = dict_full["info"]["next_edition"]
        prgrm = next_prgrm
        for k, v in dict_full["jsons"][prgrm]["info"]["info"].items():
            dict_full['info'][k] = v
        dict_full["info"]["synth_order"] = construct_synth_order(dict_full)
        dict_full["info"]["json_to_load"] = construct_lowest_json_to_load(dict_full)

        update_args_dict(dict_full)

        #reset the buttons to be 0 again
        prgrm        = dict_full["info"]["prgrm"]
        json_to_load = dict_full["info"]["json_to_load"]
        for obj, obj_dict in dict_full["jsons"][prgrm][str(json_to_load)].items():
            extra = obj_dict["extra"]
            if("reset_to_zero" in extra.keys()):
                if(obj in dict_full["obj_vals"]):
                    dict_full["obj_vals"][obj] = 0

        #start new

        save_when_necessary(dict_full, excludes=["universal"])
        send_obj_fun(dict_full, "startup", 1, True)
        if(press_all):
            for obj, val in dict_full["obj_vals"].items():
                if(obj.isnumeric()):
                    send_obj_fun(dict_full, str(obj), val, True)
                

def clean_start(dict_full, free_all = False):
    client = dict_full["client"]
    if(free_all):
        for i in range(10000):
            client.send_message("/n_free", [1000+i])
            
    start_when_necessary(dict_full, dict_full["info"]["prgrm"], True)

def send_obj_fun(dict_full, obj_key, val, action=False):
    client = dict_full["client"]
    troopers = dict_full["troopers"]
    prgrm = dict_full["info"]["prgrm"]
    json_to_load = dict_full["info"]["json_to_load"]
    dict_obj = dict_full["jsons"][prgrm][str(json_to_load)][obj_key]
    info = dict_full["info"]
    markers = dict_obj["markers"]
    args_dict = dict_full["args_dict"]
    extra = dict_obj["extra"]
    dict_info = dict_full["info"]   
    val100 = val*100
    #update args
    if(len(markers) != 0):
        boundaries = boundary_markers(markers, val100)
        val_specs = linlin(val100, float(boundaries[0]), float(boundaries[1]), 0, 1)
        for sy_key, marker_args_vals in markers[boundaries[0]].items():
            marker_args_vals = marker_args_vals.keys()
            for arg_key in marker_args_vals:
                dict_spec = dict_full["meta"][sy_key][arg_key]
                arg_val = linlin(
                    val_specs,
                    0,
                    1,
                    markers[boundaries[0]][sy_key][arg_key],
                    markers[boundaries[1]][sy_key][arg_key]
                    )
                args_dict[sy_key][arg_key] = spec_map(arg_val, dict_spec)

            #set synth
            if(sy_key in troopers):
                target_id = troopers[sy_key]
                arg_pairs = as_pairs_puton(dict_full, sy_key)
                arg_pairs = arg_pairs + ["len", dict_info["len"], "bpm", dict_info["bpm"]]
                client.send_message("/n_set", [target_id] + arg_pairs)      

    if(action):
        #extras
        if(len(extra) != 0):
            for extra_k, extra_v in extra.items():
                #jsons jump for switch
                if(extra_k == "jsons_jump"):
                    json_to_load_new = next_jsons_jump(dict_full, val, extra_v)

                    if(str(json_to_load_new) in dict_full["jsons"][dict_full["info"]["prgrm"]].keys()):
                        json_to_load = json_to_load_new
                        dict_full["info"]["json_to_load"] = json_to_load
                        update_args_dict(dict_full)

                #toggle
                if(extra_k == "toggle"):
                    if(val > 0):
                        dict_info["toggle"] = "toggle"
                    else: 
                        dict_info["toggle"] = "momentary"
                    dict_info["momentary_checking"] = True

                if(extra_k == "tap_bpm"):
                    if(val>0):
                        new_time = time.time()
                        time_diff = new_time - dict_info["bpm_time"] 
                        if(0.027240533914464723 < time_diff < 1.75):
                            dict_info["time_diff"] = time_diff
                            dict_info["bpm"]       = 60/time_diff
                            dict_info["len"]       = sc_round(60/4/dict_info["bpm"], 1/dict_info["sr"])

                        print("bpm:", dict_info["bpm"])
                        dict_info["bpm_time"] = time.time()
                        update_args_dict(dict_full)

                if(extra_k == "prgrm_change"):
                    if(val > 0):
                        dict_info["loop_prgrm"] = "play"
                        dict_info["prgrm_time"] = time.time()
                        start_when_necessary(dict_full, dict_full["info"]["next_prgrm"])
                    if(val == 0):
                        dict_info["prgrm_time"] = 0
                    print("prgrm_time1:", dict_info['prgrm_time'])
        #startup
        if(val > 0):
            for sy_key in dict_obj["start"]:
                target_id = 0
                add_action = 3
                for sy_key_order in dict_full['info']['synth_order']:
                    if(sy_key_order in dict_full["troopers"]):
                        target_id = dict_full["troopers"][sy_key_order]
                    if(sy_key_order == sy_key):
                        break
                if(target_id == 0):
                    add_action = 0
                if(sy_key not in troopers):
                    arg_pairs = as_pairs_puton(dict_full, sy_key)
                    arg_pairs = arg_pairs + ["len", dict_info["len"], "bpm", dict_info["bpm"]]
                    #print("sy_key", sy_key, "filteradv?, id:", info["troopers_id"], "add", add_action, "target", target_id)
                    client.send_message("/s_new", [sy_key, info["troopers_id"], add_action, target_id] + arg_pairs)
                    troopers[sy_key] = info["troopers_id"]
                    info["troopers_id"] = sc_wrap(info["troopers_id"] + 1, 1000, 9999)
        
        #closedown
        if(val == 0):
            for sy_key in dict_obj["close"]:
                if(sy_key in troopers):
                    client.send_message("/n_set", [troopers[sy_key], "gate", 0])
                    #client.send_message("/n_free", [troopers[sy_key]])
                    dict_full["troopers"].pop(sy_key)

def load_dict_select_prgrm():
    dict_return = {}
    dict_return["state"] = "edition"
    dict_return["led_action_idx"] = 0
    dict_return["led_time"] = 0
    dict_return["led_time_tol"] = 0.2
    dict_return["obj_vals"] = {"0":0, "1":0}
    dict_return["made_a_change"] = False
    return dict_return
    
def load_dict_select_prgrm_reset(dict_full):
    dict_return = dict_full["modus_select"]
    dict_return["led_action_idx"] = 0
    dict_return["led_time"] = time.time()
    dict_return["obj_vals"] = {"0":0, "1":0}

def construct_synth_order(dict_full):
    dict_info = dict_full["info"]
    d = dict_full["jsons"][dict_info["prgrm"]]["info"]["synths"]
    dict_return = sorted(d, key=lambda k: d[k]['out'], reverse=True)
    return dict_return

def load_dict_full():
    dict_full = {}
    path_initialization = os.path.join(DIRECTORY, "initialization.json")
    print(path_initialization)
    with open(path_initialization, "r") as f:
        dict_full["initialization"] = json.load(f)
    dict_full["jsons"]        = load_jsons(dict_full, "jsons")
    dict_full["meta"]         = load_folder_metadata("stores")
    dict_full["syndef_paths"] = load_scsyndef_paths("stores")
    dict_full["client"]       = SimpleUDPClient("127.0.0.1", 57110)
    dict_full["modus_select"] = load_dict_select_prgrm()
    dict_full["troopers"]     = {}
    dict_full["led"]          = [0,0]
    dict_full["obj_vals"]     = {
        "0":  0,
        "1":  0,
        "2":  0,
        "3":  0,
        "4":  0,
        "5":  0,
        "6":  0.5,
        "7":  0.5,
        "8":  0.5,
        "9":  0.5,
        "10": 0.5,
        "11": 0.5,
        "startup": 1,
        "closedown": 0
        }
    dict_full["info"]         = load_info(dict_full)
    dict_full["buffers"]      = load_buffers(dict_full)

    dict_full["info"]['synth_order']  = construct_synth_order(dict_full)
    dict_full["info"]["json_to_load"] = construct_lowest_json_to_load(dict_full)

    with open(os.path.join(DIRECTORY, "gpio_map.json"), "r") as f:
        dict_full["gpio_map"] = json.load(f)
    dict_full["gpio"] = load_gpio(dict_full)
    construct_orderings(dict_full)
    update_args_dict(dict_full)
    send_load_syndef(dict_full)
    return dict_full
    
def DigitalIn(pin_number: int) -> digitalio.DigitalInOut:
    try:
        # Dynamically get board.D{pin_number}
        pin = getattr(board, f"D{pin_number}")
    except AttributeError:
        raise ValueError(f"Pin D{pin_number} does not exist on this board")

    button = digitalio.DigitalInOut(pin)
    button.direction = digitalio.Direction.INPUT
    button.pull = digitalio.Pull.UP

    return button

def load_gpio(dict_full):
    try:
        dict_return = {}
        dict_return["led"] = {}
        dict_return["obj"] = {}
        dict_return["spi"] = spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
        dict_return["cs"]  = cs = digitalio.DigitalInOut(board.D8)
        dict_return["mcp"] = MCP.MCP3008(spi, cs)

        for obj_idx, gpio in dict_full["gpio_map"]["digital"].items():
            dict_return["obj"][obj_idx] = {}
            dict_return["obj"][obj_idx]["in"] = DigitalIn(gpio["pin"])
            dict_return["obj"][obj_idx]["reverse"] = gpio["reverse"]

        for obj_idx, gpio in dict_full["gpio_map"]["analog"].items():
            dict_return["obj"][obj_idx] = {}
            dict_return["obj"][obj_idx]["in"] = AnalogIn(dict_return["mcp"], getattr(MCP, f'P{gpio["pin"]}'))
            dict_return["obj"][obj_idx]["reverse"] = gpio["reverse"]
    
        for led_idx, gpio in dict_full["gpio_map"]["led"].items():
            dict_return["led"][led_idx] = {}
            dict_return["led"][led_idx] = digitalio.DigitalInOut(getattr(board, f"D{gpio["pin"]}"))
            dict_return["led"][led_idx].direction = digitalio.Direction.OUTPUT
            dict_return["led"][led_idx].value = False
          
        return dict_return
    except Exception:
        return None

def set_program(dict_full, prgrm):
    send_obj_fun(dict_full, "closedown", 0, True)
    dict_full["info"]["prgrm"] = prgrm
    update_args_dict(dict_full)
    send_obj_fun(dict_full, "startup", 1, True)

def loop_val_check(dict_full, obj_i, val_read):
    remember_vals = dict_full["info"]["remember_vals"]
    val_change_cond = False
    val_prev = dict_full["obj_vals"][str(obj_i)]
    val_tol  = 0.03
    is_analog = str(obj_i) in dict_full["gpio_map"]["analog"]

    if(obj_i not in [0, 1]):
        val_diff = abs(val_read - val_prev)
        val_change_cond = val_diff>val_tol
        if(is_analog):
            val_change_cond = val_change_cond and not (((val_read == 0) and (val_prev > 0.1)) or ((val_read == 1) and (val_prev < 0.9)))

        if(val_change_cond):
            dict_full["obj_vals"][str(obj_i)] = val_read
    
    if(obj_i in [0, 1]):
        if(dict_full["info"]["toggle"] == "toggle"):
            if(val_read>0):
                if(val_read != remember_vals[obj_i]):
                    val_change_cond = True
                    dict_full["obj_vals"][str(obj_i)] = 1 - dict_full["obj_vals"][str(obj_i)]      
        else:
            dict_full["obj_vals"][str(obj_i)] = val_read
            val_diff = abs(val_read - val_prev)
            val_change_cond = val_diff>val_tol

        if(dict_full["info"]["momentary_checking"]):
            dict_full["obj_vals"][str(obj_i)] = val_read
    remember_vals[obj_i] = val_read
    
    return val_change_cond


def letter_to_morse(letter):
    dict_morse = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.',
    'F': '..-.', 'G': '--.', 'H': '....', 'I': '..', 'J': '.---',
    'K': '-.-', 'L': '.-..', 'M': '--', 'N': '-.', 'O': '---',
    'P': '.--.', 'Q': '--.-', 'R': '.-.', 'S': '...',
    'T': '-', 'U': '..-', 'V': '...-', 'W': '.--',
    'X': '-..-', 'Y': '-.--', 'Z': '--..',
    '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....',
    '7': '--...', '8': '---..', '9': '----.',
    '0': '-----',
    ' ': '/'
    }
    morse = [dict_morse[l.capitalize()] for l in letter]
    return "  ".join(morse)

def morse_to_array(morse: str) -> list[int]:
    result = []
    for char in morse:
        if char == '-':
            result += [0, 1, 1]
        elif char == '.':
            result += [0, 1]
        else:
            result += [0]
    result.append(0)
    return result


def edition_to_own_morse(edition):
    if(type(edition) == int):
        edition = int(edition)
        mod = 4
        dashes = math.floor(edition/mod)
        dots = edition%mod
        own_morse = ("-"*dashes) + ("."*dots)
    else:
        own_morse = letter_to_morse(edition)
    return(own_morse)

def letter_to_morse_to_array(letter):
    morse = letter_to_morse(letter)
    return morse_to_array(morse)

def modus_select_led_state(dict_full, morse, led_idxs, repeat = False):
    morse_array = morse_to_array(morse)
    dict_modus_select = dict_full["modus_select"]
    if(time.time() - dict_modus_select["led_time"] > dict_modus_select["led_time_tol"]):
        if(dict_modus_select["led_action_idx"] == 0):
            for i in range(len(dict_full["led"])):
                dict_full["led"][i] = 0    
        for i in led_idxs:
            dict_full["led"][i] = morse_array[dict_modus_select["led_action_idx"]]
        dict_modus_select["led_time"] = time.time()
        dict_modus_select["led_action_idx"] += 1
    if(dict_modus_select["led_action_idx"] == len(morse_array)):
        if(not(repeat)):
            dict_modus_select["state"] = "prgrm"
        load_dict_select_prgrm_reset(dict_full)

def extra_from_obj_any(dict_full, obj):
    prgrm = dict_full["info"]["prgrm"]
    data = list(dict_full["jsons"][prgrm].values())[0]
    return data[obj]["extra"]

def find_obj_jsons_jump(dict_full):
    prgrm = dict_full["info"]["prgrm"]
    data = list(dict_full["jsons"][prgrm].values())[0]
    result = [key for key, val in data.items() if 'jsons_jump' in val.get('extra', {})]
    return result[0]

def construct_lowest_json_to_load(dict_full):
    prgrm = dict_full["info"]["prgrm"]
    return str(min([int(jtl) for jtl in dict_full["jsons"][prgrm].keys() if jtl.isnumeric()]))
    
def next_jsons_jump(dict_full, val, extra_v, from_start = False):
    if(len(extra_v) == 1):
        extra_v_nobug = extra_v.copy()*2
    elif(len(extra_v) % 2 == 1):
        extra_v_nobug = extra_v[:-1].copy()
    else:
        extra_v_nobug = extra_v.copy()

    json_to_load = dict_full["info"]["json_to_load"]
    uneven = int(bool(val))
    if(json_to_load in extra_v_nobug):
        index = extra_v_nobug.index(json_to_load)
    else:
        index = 0

    if(from_start):
        index = 0
    
    if(index%2 != uneven):
        index = index + 1

    json_to_load_new = int(extra_v_nobug[index%len(extra_v_nobug)])
    dict_full["info"]["json_to_load"] = json_to_load_new
    return json_to_load_new

def next_prgrm(dict_full, ordering_idx, from_start = False):
    if(ordering_idx == 0):
        orderings = dict_full['info']['next_orderings_synth']
    else:
        orderings = dict_full['info']['next_orderings_fx']
    prgrm = dict_full["info"]["next_prgrm"]
    values = [orderings[k] for k in sorted(orderings)]
    if (from_start or (prgrm not in values)):
        idx = 0
    else:
        idx = (values.index(prgrm) + 1) % len(values)
    print("test", orderings, idx)
    dict_full["info"]["next_ordering"] = sorted(orderings)[idx]
    dict_full["info"]["next_prgrm"]    = values[idx]
    return values[idx]

def next_edition(dict_full, from_start = False):
    editions = dict_full["info"]["editions"]
    edition  = dict_full["info"]["next_edition"]
    idx = 0
    if((edition in editions) and not(from_start)):
        idx = (editions.index(edition)+1)%len(editions)
    edition_new = dict_full["info"]["editions"][idx]
    dict_full["info"]["next_edition"] = edition_new
    construct_orderings(dict_full)
    return edition_new

def mode_select(dict_full, obj_i, val_read):
    morse_pause = dict_full["info"]["morse_pause"]
    # prgrm = dict_full["info"]["prgrm"]
    prgrm = dict_full["info"]["next_prgrm"]
    if(dict_full["modus_select"]["state"] == "edition"):
        #edition = dict_full["info"]["edition"]
        edition = dict_full["info"]["next_edition"]
        modus_select_led_state(dict_full, edition_to_own_morse(edition) + morse_pause, [0, 1], True)
    
    if(dict_full["modus_select"]["state"] == "prgrm"):
        ordering = dict_full["jsons"][prgrm]["info"]["info"]["ordering"]
        line     = dict_full["jsons"][prgrm]["info"]["info"]["line"]
        led_array = [0] if (line == "synth") else [1]
        modus_select_led_state(dict_full, letter_to_morse(ordering) + morse_pause, led_array, True)

    if(obj_i in [0,1]):
        if(dict_full["modus_select"]["obj_vals"][str(obj_i)] != val_read):
            if(val_read > 0):
                if(dict_full["modus_select"]["state"] == "edition"):
                    next_edition(dict_full)
                    prgrm = next_prgrm(dict_full, 0, from_start=True)
                    #obj_jj = find_obj_jsons_jump(dict_full)
                    #next_jsons_jump(dict_full, dict_full["obj_vals"][obj_jj], extra_from_obj_any(dict_full, obj_jj)["jsons_jump"], from_start = True)
                if(dict_full["modus_select"]["state"] == "prgrm"):
                    prgrm = next_prgrm(dict_full, obj_i)
                load_dict_select_prgrm_reset(dict_full)
                print("pressed", dict_full["modus_select"]["state"], prgrm)
        dict_full["modus_select"]["obj_vals"][str(obj_i)] = val_read


def loop_prgrm(dict_full, print_status = False):
    obj_i = 0
    sleep_time = dict_full["info"]["sleep"]
    pedal_obj_n = dict_full["info"]["pedal_obj_n"]
    idx = 0
    gpio_available = dict_full["gpio"] != None

    while True:
        obj_i = idx % pedal_obj_n
        prgrm = dict_full["info"]["prgrm"]
        json_to_load = dict_full["info"]["json_to_load"]
        objs = dict_full["jsons"][prgrm][str(json_to_load)]
        objs_i_with_prgrm_change = [int(k) for k, v in objs.items() if k.isnumeric() and "prgrm_change" in v["extra"]]
        loop_prgrm = dict_full["info"]["loop_prgrm"]
        
        if(obj_i == 0 and print_status):
            clear_output(wait=True)
            print(int(dict_full["led"][0]), int(dict_full["led"][1]))
            print(f"loop_prgrm: {loop_prgrm}, toggle: {dict_full["info"]["toggle"]}")
            print(f"prgrm: {prgrm}, json: {dict_full["info"]["json_to_load"]}, state: {dict_full["modus_select"]["state"]}, ordering: {dict_full["info"]["ordering"]}, edition: {dict_full["info"]["edition"]}")
            print(f"time_diff: {dict_full["info"]["time_diff"]}, bpm: {dict_full["info"]["bpm"]}, len: {dict_full["info"]["len"]}")
            print(f"prgrm: {dict_full["info"]["next_prgrm"]} -> {dict_full["info"]["prgrm"]}")
        
        val_read = read_pedal_inputs(dict_full, obj_i, from_csv = not gpio_available)

        if(loop_prgrm == "modus_select"):
            mode_select(dict_full, obj_i, val_read)

        #play things
        if((loop_prgrm == "play") or ((obj_i in objs_i_with_prgrm_change + [10, 11]) and (obj_i not in [0, 1]))):
            val_change_cond = loop_val_check(dict_full, obj_i, val_read)
            if(val_change_cond):
                val = dict_full["obj_vals"][str(obj_i)]
                send_obj_fun(dict_full, str(obj_i), val, True)
                print(obj_i, val)
            
            if(obj_i in objs_i_with_prgrm_change):
                if(
                    (val_read == 1)
                    and (time.time() - dict_full["info"]["prgrm_time"] > 2.0)
                    ):
                    print(time.time())
                    print("prgrm_time2:", dict_full["info"]['prgrm_time'])
                    print("mode select")
                    if(dict_full["info"]["loop_prgrm"] != "modus_select"):
                        dict_full["modus_select"]["state"] = "edition"
                        load_dict_select_prgrm_reset(dict_full)
                    dict_full["info"]["loop_prgrm"] = "modus_select"
                    start_when_necessary(dict_full, "universal", necessary = False, press_all = False)
                
                if(val_read == 0):
                    if(dict_full["modus_select"]["state"] != "prgrm"):
                        load_dict_select_prgrm_reset(dict_full)
                    dict_full["modus_select"]["state"] = "prgrm"
            dict_full["info"]["momentary_checking"] = False
            
            
            
        #pure play only
        if(loop_prgrm == "play"):
            dict_full["led"][0] = dict_full["obj_vals"]["0"]
            dict_full["led"][1] = dict_full["obj_vals"]["1"]

        #check led
        if(gpio_available):
            for  i in range(2):
                dict_full["gpio"]["led"][str(i)].value = bool(dict_full["led"][i])
        sleep(sleep_time)
        idx = idx + 1