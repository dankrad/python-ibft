from bls_threshold import generate_keys
import json
import argparse

parser = argparse.ArgumentParser(description='Run Istanbul BFT process.')
parser.add_argument('--parties', metavar='parties_json', type=str, default="parties.json",
                    help='JSON configuring the parties')
parser.add_argument('--config', metavar='config_json', type=str, default="config.json",
                    help='JSON configuration')
args = parser.parse_args()

ibft_config = json.load(open(args.config, "r"))
ibft_parties = json.load(open(args.parties, "r"))

ibft_t = ibft_config["ibft_t"]
ibft_n = ibft_config["ibft_n"]

aggregate_public, public, private = generate_keys(ibft_n, 2 * ibft_t)

for i, party in enumerate(ibft_parties):
    party["public_key"] = "0x" + public[i].hex()
    json.dump({"private_key": private[i]}, open("privkey_{0}.json".format(i), "w"))

json.dump(ibft_parties, open(args.parties, "w"))