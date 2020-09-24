from flask import Flask, json, request, make_response, jsonify
import requests
from collections import defaultdict
import sys, os
import _thread, threading
from queue import Queue
import random
import time
import argparse
if __name__ == '__main__':
    from bls_threshold import py_ecc_bls, reconstruct, get_aggregate_key
else:
    from .bls_threshold import py_ecc_bls, reconstruct, get_aggregate_key

def ibft_leader(l, r):
    return (l + r) % ibft_n

def ibft_send_message(url, msg):
    try:
        requests.post(url, json=msg)
    except:
        pass

def send_broadcast(msg):
    ibft_send_messages(msg, is_broadcast=True)

def ibft_send_messages(msg, endpoint="message", justification=None, destination_party=None, is_broadcast=False):
    signature = py_ecc_bls.Sign(ibft_privkey, bytes(json.dumps(msg), encoding="utf=8"))
    wrapped_message = {"message": msg, "sender": ibft_id, "signature": "0x" + signature.hex(), "justification": justification, "broadcast": is_broadcast}
    for i, party in enumerate(ibft_parties):
        if destination_party == None or destination_party == i:
            if __name__ == '__main__' and args.random_values and "value" in msg:
                msg_copy = msg.copy()
                msg_copy["value"] = str(random.randint(0, 10))
                wrapped_message_copy = wrapped_message.copy()
                wrapped_message_copy["message"] = msg_copy
                signature = py_ecc_bls.Sign(ibft_privkey, bytes(json.dumps(msg_copy), encoding="utf=8"))
                wrapped_message_copy["signature"] = "0x" + signature.hex()
                _thread.start_new_thread(ibft_send_message, (party["url"] + endpoint, wrapped_message_copy))
                continue
            _thread.start_new_thread(ibft_send_message, (party["url"] + endpoint, wrapped_message))

def ibft_instance():
    return {"round": 0, 
               "prepared_round": None, 
               "prepared_value": None,
               "input_value": None,
               "prepare_messages": defaultdict(dict),
               "prepare_messages_quorum_achieved": defaultdict(bool),
               "prepared_signatures": defaultdict(dict),
               "commit_messages": defaultdict(dict),
               "commit_messages_quorum_achieved": defaultdict(bool),
               "round_change_messages": defaultdict(lambda: defaultdict(dict)),
               "round_change_messages_quorum_achieved": defaultdict(bool),
               "round_change_message_justifications": defaultdict(dict),
            }

def ibft_initiate_round_change(l):
    if ibft_instances[l]["prepared_round"] != None:
        print("Nonzero prepared round, computing justification")
        prepared_justification_message = ibft_instances[l]["prepared_justification_message"]
        signature = reconstruct({k: bytes.fromhex(x[2:]) 
                    for k, x in ibft_instances[l]["prepare_messages"][json.dumps(prepared_justification_message)].items()})
        justification = {"message": prepared_justification_message,
                         "aggregate_signature": "0x" + signature.hex()}
    else:
        justification = None

    broadcast_message = {"type": "round-change",
                            "lambda": l,
                            "round": ibft_instances[l]["round"],
                            "prepared_round": ibft_instances[l]["prepared_round"],
                            "prepared_value": ibft_instances[l]["prepared_value"]}
    ibft_send_messages(broadcast_message, justification=justification)


def ibft_timer():
    print(".", end='', flush=True)
    for l, instance in ibft_instances.items():
        if "timer" in instance:
            instance["timer"] -= ibft_timer_granularity
            if instance["timer"] <= 0:
                print("Timeout on instance {0} for round {1}".format(l, instance["round"]))
                instance["round"] += 1
                instance["timer"] = ibft_start_time * 2 ** instance["round"]
                ibft_initiate_round_change(l)

    threading.Timer(ibft_timer_granularity / 1000, ibft_timer).start()


def start_instance(instance_id, input_value, validity_callback=None, decision_callback=None):
    l = instance_id
    ibft_instances[l]["input_value"] = input_value
    ibft_instances[l]["timer"] = ibft_start_time
    ibft_instances[l]["validity_callback"] = validity_callback
    ibft_instances[l]["decision_callback"] = decision_callback
    if ibft_leader(l, 0) == ibft_id:
        broadcast_message = {"type": "pre-prepare",
                               "lambda": l,
                               "round": 0,
                               "value": input_value}
        ibft_send_messages(broadcast_message)


def run_server():
    ibft_timer()
    _thread.start_new_thread(ibft_process_events, ())
    _thread.start_new_thread(lambda: api.run(port=ibft_parties[ibft_id]["port"], threaded=False, processes=1), ())


ibft_instances = defaultdict(ibft_instance)
ibft_message_queue = Queue()
broadcast_callback = None

api = Flask(__name__)

def ibft_process_events():
    while True:
        wrapped_message = ibft_message_queue.get()
        try:
            msg = wrapped_message["message"]
            sender = wrapped_message["sender"]
            signature = wrapped_message["signature"]
            if not py_ecc_bls.Verify(bytes.fromhex(ibft_parties[sender]["public_key"][2:]),
                bytes(json.dumps(msg), encoding="utf-8"),
                bytes.fromhex(signature[2:])):
                print("Got message with invalid signature, ignored")
                continue
            if wrapped_message["broadcast"]:
                if broadcast_callback != None:
                    broadcast_callback(wrapped_message["message"], wrapped_message["sender"])
                continue
            l = msg["lambda"]
            if "decided" in ibft_instances[l]:
                if msg["type"] == "round-change":
                    justification = {"message": ibft_instances[l]["decision_message"],
                                "aggregate_signature": ibft_instances[l]["decision_signature"]}

                    decision_message = {"type": "decide",
                                    "lambda": l,
                                    "value": ibft_instances[l]["decided"]}
                    ibft_send_messages(decision_message, justification=justification, destination_party=sender)
                    print("Got round change after deciding, sending quorum")
                print("Got message after deciding, ignored")
                continue
            if msg["type"] == "pre-prepare":
                if msg["round"] != ibft_instances[l]["round"]:
                    print("Got pre-prepare for round {0} but current round is {1}, ignored".format(msg["round"], ibft_instances[l]["round"]))
                    continue
                print("Received pre-prepare")
                if msg["round"] > 0:
                    # Check justification
                    # Check quorum of round-change messages included
                    pr = None
                    pv = None
                    for m in wrapped_message["justification"]["round_change_messages"]:
                        if not py_ecc_bls.Verify(bytes.fromhex(ibft_parties[m["sender"]]["public_key"][2:]),
                                bytes(json.dumps(m["message"]), encoding="utf-8"),
                                bytes.fromhex(m["signature"][2:])) or \
                                not m["message"]["round"] >= msg["round"]:
                            print("Bad pre-prepare justification, ignored")
                            continue
                        if m["message"]["prepared_round"] != None and (pr == None or m["message"]["prepared_round"] > pr):
                            pr = m["message"]["prepared_round"]
                            pv = m["message"]["prepared_value"]

                    if pv != None and not pv == msg["value"]:
                        print("Bad pre-prepare justification, ignored")
                        continue

                    if pr != None:
                        # Quorum of pre-prepare messages included for highest prepared round
                        if not (wrapped_message["justification"]["pre_prepare_messages"]["message"]["round"] == pr and \
                                wrapped_message["justification"]["pre_prepare_messages"]["message"]["value"] == pv):
                            print("Bad pre-prepare justification, ignored")
                            continue

                        if not py_ecc_bls.Verify(ibft_threshold_pubkey,
                                            bytes(json.dumps(wrapped_message["justification"]["pre_prepare_messages"]["message"]), encoding="utf-8"),
                                            bytes.fromhex(wrapped_message["justification"]["pre_prepare_messages"]["aggregate_signature"][2:])):
                            print("Bad pre-prepare justification, ignored")
                            continue

                broadcast_message = {"type": "prepare",
                        "lambda": l,
                        "round": msg["round"],
                        "value": msg["value"]}
                ibft_send_messages(broadcast_message)
            elif msg["type"] == "prepare":
                if msg["round"] != ibft_instances[l]["round"]:
                    print("Got pre-prepare for round {0} but current round is {1}, ignored".format(msg["round"], ibft_instances[l]["round"]))
                    continue
                msg_tuple = json.dumps(msg)
                ibft_instances[l]["prepare_messages"][msg_tuple][sender] = signature
                if len(ibft_instances[l]["prepare_messages"][msg_tuple]) > 2 * ibft_t \
                    and not ibft_instances[l]["prepare_messages_quorum_achieved"][msg_tuple]:
                    print("Received prepare quorum")
                    ibft_instances[l]["prepare_messages_quorum_achieved"][msg_tuple] = True
                    ibft_instances[l]["prepared_round"] = msg["round"]
                    ibft_instances[l]["prepared_value"] = msg["value"]
                    ibft_instances[l]["prepared_justification_message"] = msg
                    if __name__ == '__main__' and args.offline_after_prepare:
                        print("Going offline")
                        os._exit(0)
                    broadcast_message = {"type": "commit",
                    "lambda": msg["lambda"],
                    "round": msg["round"],
                    "value": msg["value"]}
                    ibft_send_messages(broadcast_message)
            elif msg["type"] == "commit":
                msg_tuple = json.dumps(msg)
                ibft_instances[l]["commit_messages"][msg_tuple][sender] = signature
                if len(ibft_instances[l]["commit_messages"][msg_tuple]) > 2 * ibft_t  \
                    and not ibft_instances[l]["commit_messages_quorum_achieved"][msg_tuple]:
                    print("Received commit quorum")
                    ibft_instances[l]["commit_messages_quorum_achieved"][msg_tuple] = True
                    if "timer" in ibft_instances[l]:
                        del ibft_instances[l]["timer"]
                    ibft_instances[l]["decided"] = msg["value"]
                    print("Decided on lambda={0}, value={1}".format(msg["lambda"], msg["value"]))
                    if ibft_instances[l]["decision_callback"] != None:
                        ibft_instances[l]["decision_callback"](msg["value"])

                    ibft_instances[l]["decision_message"] = msg
                    ibft_instances[l]["decision_signature"] = "0x" + reconstruct({k: bytes.fromhex(x[2:]) 
                            for k, x in ibft_instances[l]["commit_messages"][msg_tuple].items()}).hex()

            elif msg["type"] == "round-change":
                if msg["prepared_round"] != None and not (msg["prepared_round"] < msg["round"]):
                    return make_response(jsonify(False), 400)
                if msg["prepared_round"] != None or msg["prepared_value"] != None:
                    if msg["prepared_round"] != wrapped_message["justification"]["message"]["round"] or \
                            msg["prepared_value"] != wrapped_message["justification"]["message"]["value"] or \
                            wrapped_message["justification"]["message"]["type"] != "prepare":
                        print("Bad round change justification, ignored")
                        continue
                    if not py_ecc_bls.Verify(ibft_threshold_pubkey,
                                        bytes(json.dumps(wrapped_message["justification"]["message"]), encoding="utf-8"),
                                        bytes.fromhex(wrapped_message["justification"]["aggregate_signature"][2:])):
                        print("Bad round change justification, ignored")
                        continue
                    ibft_instances[l]["round_change_message_justifications"][json.dumps(msg)] = wrapped_message["justification"]

                ibft_instances[l]["round_change_messages"][msg["round"]][sender] = {
                            "sender": sender,
                            "signature": signature,
                            "message": msg}
                maxround = max(ibft_instances[l]["round_change_messages"])
                oldround = ibft_instances[l]["round"]
                if maxround > ibft_instances[l]["round"]:
                    msgset = {}
                    for r in range(maxround, ibft_instances[l]["round"], -1):
                        for s, m in ibft_instances[l]["round_change_messages"][r].items():
                            if s not in msgset:
                                msgset[s] = ibft_instances[l]["round_change_messages"][r][s]
                        if len(msgset) > ibft_t:
                            ibft_instances[l]["round"] = r
                            ibft_instances[l]["timer"] = ibft_start_time * 2 ** r

                            ibft_initiate_round_change(l)
                            break
                
                if len(ibft_instances[l]["round_change_messages"][msg["round"]]) > 2 * ibft_t  \
                    and ibft_leader(l, msg["round"]) == ibft_id \
                    and not ibft_instances[l]["round_change_messages_quorum_achieved"][msg["round"]]:
                    ibft_instances[l]["round_change_messages_quorum_achieved"][msg["round"]] = True
                    print("Assuming leader for instance {0} round {1}".format(l, msg["round"]))

                    pr = None
                    pv = None
                    pre_prepare_justification = None
                    for m in ibft_instances[l]["round_change_messages"][msg["round"]].values():
                        if m["message"]["prepared_round"] != None and (pr == None or m["message"]["prepared_round"] > pr):
                            pr = m["message"]["prepared_round"]
                            pv = m["message"]["prepared_value"]
                            pre_prepare_justification = ibft_instances[l]["round_change_message_justifications"][json.dumps(m["message"])]

                    if pv == None:
                        if ibft_instances[l]["input_value"] == None:
                            print("I have no input value. Not started, not assuming leadership")
                            return make_response(jsonify(True), 200)
                        pv = ibft_instances[l]["input_value"]

                    broadcast_message = {"type": "pre-prepare",
                                        "lambda": l,
                                        "round": msg["round"],
                                        "value": pv}

                    justification = {"pre_prepare_messages": pre_prepare_justification,
                                    "round_change_messages": list(ibft_instances[l]["round_change_messages"][msg["round"]].values())}

                    ibft_send_messages(broadcast_message, justification=justification)
            elif msg["type"] == "decide":
                if wrapped_message["justification"]["message"]["type"] != "commit" or \
                        msg["value"] != wrapped_message["justification"]["message"]["value"]:
                    print("Bad decide justification, ignored")
                    continue

                if not py_ecc_bls.Verify(ibft_threshold_pubkey,
                                    bytes(json.dumps(wrapped_message["justification"]["message"]), encoding="utf-8"),
                                    bytes.fromhex(wrapped_message["justification"]["aggregate_signature"][2:])):
                    print("Bad decide justification, ignored")
                    continue
                ibft_instances[l]["decided"] = msg["value"]
                ibft_instances[l]["decision_message"] = wrapped_message["justification"]["message"]
                ibft_instances[l]["decision_signature"] = wrapped_message["justification"]["aggregate_signature"]
                if "timer" in ibft_instances[l]:
                    del ibft_instances[l]["timer"]
                print("Decided via 'decide' message on lambda={0}, value={1}".format(l, msg["value"]))
                if ibft_instances[l]["decision_callback"] != None:
                    ibft_instances[l]["decision_callback"](msg["value"])
            else:
                print("Bad message type, ignored")
                continue
        except:
            print("Error processing message, ignored")

@api.route('/message', methods=['POST'])
def post_message():
    wrapped_message = request.json
    ibft_message_queue.put(wrapped_message)
    return make_response(jsonify(True), 200)

@api.route('/instances', methods=['GET'])
def get_instances():
    return make_response(jsonify(ibft_instances), 200)

@api.route('/instance/<int:instance_id>/', methods=['GET'])
def get_instance(instance_id):
    return make_response(jsonify(ibft_instances[instance_id]), 200)

@api.route('/online', methods=['GET'])
def get_online():
    return make_response(jsonify(True), 200)

@api.route('/parties', methods=['GET'])
def get_parties():
    return make_response(jsonify(ibft_parties), 200)

@api.route('/id', methods=['GET'])
def get_id():
    return make_response(jsonify(ibft_id), 200)

def load_config(parties_file, config_file, privkey_file, process_id):
    global ibft_id, ibft_parties, ibft_t, ibft_n, ibft_start_time, ibft_timer_granularity, ibft_threshold_pubkey, ibft_privkey

    ibft_id = process_id

    privkey_json = json.load(open(privkey_file, "r"))

    ibft_privkey = privkey_json["private_key"]

    ibft_parties = json.load(open(parties_file, "r"))
    ibft_config = json.load(open(config_file, "r"))

    ibft_t = ibft_config["ibft_t"]
    ibft_n = ibft_config["ibft_n"]

    ibft_start_time = ibft_config["ibft_start_time"] # Milliseconds
    ibft_timer_granularity = ibft_config["ibft_timer_granularity"]
    ibft_threshold_pubkey = get_aggregate_key({k: bytes.fromhex(v["public_key"][2:]) for k, v in enumerate(ibft_parties[:2 * ibft_t + 1])})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run Istanbul BFT process.')
    parser.add_argument('process_id', metavar='process_id', type=int, 
                        help='The ID of the process')
    parser.add_argument('--parties', metavar='parties_json', type=str, default="parties.json",
                        help='JSON configuring the parties')
    parser.add_argument('--config', metavar='config_json', type=str, default="config.json",
                        help='JSON configuration')
    parser.add_argument('--privkey', metavar='privkey_json', type=str, default="",
                        help='JSON configuration')
    parser.add_argument('--input-value', metavar='input_value', type=str, default="",
                        help='Use as input value')
    parser.add_argument("--offline",dest='offline',action='store_true', help="Defect mode: this process is offline.")
    parser.add_argument("--random-values",dest='random_values',action='store_true', help="Defect mode: this process will send random values in messages.")
    parser.add_argument("--online-delayed",dest='online_delayed',action='store_true', help="Defect mode: Only come online after 60 seconds.")
    parser.add_argument("--offline-delayed",dest='offline_delayed',action='store_true', help="Defect mode: Go offline after 60 seconds.")
    parser.add_argument("--offline-after-prepare",dest='offline_after_prepare',action='store_true', help="Defect mode: Go offline after first round is prepared.")

    args = parser.parse_args()

    ibft_id = args.process_id
    print("I am IBFT process {0}".format(ibft_id))

    if args.online_delayed:
        print("Waiting 60s to go online")
        time.sleep(60)
        print("Now online")

    if args.offline_delayed:
        print("Will go offline after 60s")
        def go_offline():
            print("Going offline")
            os._exit(0)

        threading.Timer(60, go_offline).start()

    if args.privkey == "":
        privkey_file = "privkey_{0}.json".format(ibft_id)
    else:
        privkey_file = args.privkey

    load_config(args.parties, args.config, privkey_file, ibft_id)

    if not args.offline:
        run_server()
        start_instance(0, args.input_value)
    else:
        print("I'm offline, doing nothing")
        input()