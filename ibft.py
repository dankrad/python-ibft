from flask import Flask, json, request, make_response, jsonify
import requests
from collections import defaultdict
import sys, os
import _thread, threading
import random
import time
import argparse

def ibft_leader(l, r):
    return (l + r) % ibft_n

def ibft_send_message(url, msg):
    try:
        requests.post(url, json=msg)
    except:
        pass

def ibft_broadcast(msg, endpoint="message"):
    wrapped_message = {"message": msg, "sender": ibft_id, "signature": ""}
    for party in ibft_parties:
        if args.random_values and "value" in msg:
            msg_copy = msg.copy()
            msg_copy["value"] = str(random.randint(0, 10))
            wrapped_message_copy = wrapped_message.copy()
            wrapped_message_copy["message"] = msg_copy
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
               "commit_messages": defaultdict(dict),
               "commit_messages_quorum_achieved": defaultdict(bool),
               "round_change_messages": defaultdict(lambda: defaultdict(dict)),
               "round_change_messages_quorum_achieved": defaultdict(bool),
            }

def ibft_timer():
    print(".", end='', flush=True)
    for l, instance in ibft_instances.items():
        if "timer" in instance:
            instance["timer"] -= ibft_timer_granularity
            if instance["timer"] <= 0:
                print("Timeout on instance {0} for round {1}".format(l, instance["round"]))
                instance["round"] += 1
                instance["timer"] = ibft_start_time * 2 ** instance["round"]
                broadcast_message = {"type": "round-change",
                                       "lambda": l,
                                       "round": instance["round"],
                                       "prepared_round": instance["prepared_round"],
                                       "prepared_value": instance["prepared_value"],
                # TODO: Round change justification
                                       "justification": [] }
                ibft_broadcast(broadcast_message)

    threading.Timer(ibft_timer_granularity / 1000, ibft_timer).start()

ibft_instances = defaultdict(ibft_instance)

api = Flask(__name__)

@api.route('/start', methods=['POST'])
def post_start():
    msg = request.json
    l = msg["lambda"]
    if "decided" in ibft_instances[l]:
        # TODO: Send deciding quorum to originating node
        return make_response(jsonify(False), 400)   
    value = msg["value"]
    ibft_instances[l]["input_value"] = value
    ibft_instances[l]["timer"] = ibft_start_time
    if ibft_leader(l, 0) == ibft_id:
        broadcast_message = {"type": "pre-prepare",
                               "lambda": l,
                               "round": 0,
                               "value": value}
        ibft_broadcast(broadcast_message)
    return make_response(jsonify(True), 200)


@api.route('/message', methods=['POST'])
def post_message():
    wrapped_message = request.json
    msg = wrapped_message["message"]
    sender = wrapped_message["sender"]
    # TODO: Check signature
    signature = wrapped_message["signature"]
    l = msg["lambda"]
    if "decided" in ibft_instances[l]:
        if msg["type"] == "round-change":
            # TODO: Send deciding quorum to originating node
            pass
        return make_response(jsonify(False), 400)   
    if msg["type"] == "pre-prepare":
        print("Received pre-prepare")
        # TODO: Check that pre-prepare is justified
        justified = True
        if justified:
            broadcast_message = {"type": "prepare",
                   "lambda": l,
                   "round": msg["round"],
                   "value": msg["value"]}
            ibft_broadcast(broadcast_message)
    elif msg["type"] == "prepare":
        msg_tuple = str((msg["lambda"], msg["round"], msg["value"]))
        ibft_instances[l]["prepare_messages"][msg_tuple][sender] = {"signature": signature}
        if len(ibft_instances[l]["prepare_messages"][msg_tuple]) > 2 * ibft_t \
            and not ibft_instances[l]["prepare_messages_quorum_achieved"][msg_tuple]:
            print("Received prepare quorum")
            ibft_instances[l]["prepare_messages_quorum_achieved"][msg_tuple] = True
            ibft_instances[l]["prepared_round"] = msg["round"]
            ibft_instances[l]["prepared_value"] = msg["value"]
            broadcast_message = {"type": "commit",
               "lambda": msg["lambda"],
               "round": msg["round"],
               "value": msg["value"]}
            ibft_broadcast(broadcast_message)    
    elif msg["type"] == "commit":
        msg_tuple = str((msg["lambda"], msg["round"], msg["value"]))
        ibft_instances[l]["commit_messages"][msg_tuple][sender] = {"signature": signature}
        if len(ibft_instances[l]["commit_messages"][msg_tuple]) > 2 * ibft_t  \
            and not ibft_instances[l]["commit_messages_quorum_achieved"][msg_tuple]:
            print("Received commit quorum")
            ibft_instances[l]["commit_messages_quorum_achieved"][msg_tuple] = True
            if "timer" in ibft_instances[l]:
                del ibft_instances[l]["timer"]
            ibft_instances[l]["decided"] = msg["value"]
            print("Decided on lambda={0}, value={1}".format(msg["lambda"], msg["value"]))
            # TODO: Send decided messages to other instances on round change
    elif msg["type"] == "round-change":
        if not (msg["prepared_round"] < msg["round"]):
            return make_response(jsonify(False), 400)

        ibft_instances[l]["round_change_messages"][msg["round"]][sender] = {
                    "signature": signature,
                    "round": msg["round"],
                    "prepared_round": msg["prepared_round"],
                    "prepared_value": msg["prepared_value"]}
        maxround = max(ibft_instances[l]["round_change_messages"])
        oldround = ibft_instances[l]["round"]
        if maxround > ibft_instances[l]["round"]:
            msgset = {}
            for r in range(maxround, ibft_instances[l]["round"], -1):
                for sender, msg in ibft_instances[l]["round_change_messages"][r].items():
                    if sender not in msgset:
                        msgset[sender] = ibft_instances[l]["round_change_messages"][r][sender] = msg
                if len(msgset) > ibft_t:
                    ibft_instances[l]["round"] = r
                    ibft_instances[l]["timer"] = ibft_start_time * 2 ** r
                    broadcast_message = {"type": "round-change",
                                           "lambda": l,
                                           "round": r,
                                           "prepared_round": ibft_instances[l]["prepared_round"],
                                           "prepared_value": ibft_instances[l]["prepared_value"],
                    # TODO: Round change justification
                                           "justification": [] }
                    ibft_broadcast(broadcast_message)                    
                    break
           
        if len(ibft_instances[l]["round_change_messages"][msg["round"]]) > 2 * ibft_t  \
            and ibft_leader(l, msg["round"]) == ibft_id \
            and not ibft_instances[l]["round_change_messages_quorum_achieved"][msg["round"]]:
            ibft_instances[l]["round_change_messages_quorum_achieved"][msg["round"]] = True
            print("Assuming leader for instance {0} round {1}".format(l, msg["round"]))
            # TODO: Check justification
            
            # Find highest prepared round
            pr = None
            pv = None
            for m in ibft_instances[l]["round_change_messages"][msg["round"]].values():
                if pr == None or m["prepared_round"] > pr:
                    pr = m["prepared_round"]
                    pv = m["prepared_value"]
            
            if pv == None:
                if ibft_instances[l]["input_value"] == None:
                    print("I have no input value. Not started, not assuming leadership")
                    return make_response(jsonify(True), 200)
                pv = ibft_instances[l]["input_value"]

            broadcast_message = {"type": "pre-prepare",
                                   "lambda": l,
                                   "round": msg["round"],
                                   "value": pv,
                                 # TODO: Justification for pre-prepare
                                   "justification": []}
            ibft_broadcast(broadcast_message)
        
        
    else:
        return make_response(jsonify(False), 400)
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run Istanbul BFT process.')
    parser.add_argument('process_id', metavar='process_id', type=int, 
                        help='The ID of the process')
    parser.add_argument('--parties', metavar='parties_json', type=str, default="parties.json",
                        help='JSON configuring the parties')
    parser.add_argument('--config', metavar='config_json', type=str, default="config.json",
                        help='JSON configuration')
    parser.add_argument("--offline",dest='offline',action='store_true', help="Defect mode: this process is offline.")
    parser.add_argument("--random-values",dest='random_values',action='store_true', help="Defect mode: this process will send random values in messages.")
    parser.add_argument("--online-delayed",dest='online_delayed',action='store_true', help="Defect mode: Only come online after 60 seconds.")
    parser.add_argument("--offline-delayed",dest='offline_delayed',action='store_true', help="Defect mode: Go offline after 60 seconds.")

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

    ibft_parties = json.load(open(args.parties, "r"))
    ibft_config = json.load(open(args.config, "r"))

    ibft_t = ibft_config["ibft_t"]
    ibft_n = ibft_config["ibft_n"]

    ibft_start_time = ibft_config["ibft_start_time"] # Milliseconds
    ibft_timer_granularity = ibft_config["ibft_timer_granularity"]

    if not args.offline:
        ibft_timer()
        api.run(port=ibft_parties[ibft_id]["port"])
    else:
        print("I'm offline, doing nothing")
        input()