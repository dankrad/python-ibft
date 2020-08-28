from py_ecc import optimized_bls12_381 as b
from py_ecc.bls import G2ProofOfPossession as py_ecc_bls
from py_ecc.bls.g2_primatives import (
    G1_to_pubkey,
    G2_to_signature,
    signature_to_G2,
    pubkey_to_G1,
)
from py_ecc.utils import prime_field_inv
import random

def eval_poly(x, coefs):
    r = 0
    power_of_x = 1
    for c in coefs:
        r += power_of_x * c % b.curve_order
        power_of_x = power_of_x * x % b.curve_order
    return r

def generate_keys(n_parties, t):
    coefs = [random.randint(0, b.curve_order - 1) for i in range(t + 1)]
    aggregate_public = G1_to_pubkey(b.multiply(b.G1, coefs[0]))
    private = [eval_poly(x, coefs) for x in range(1, n_parties + 1)]
    public = [G1_to_pubkey(b.multiply(b.G1, x)) for x in private]
    return aggregate_public, public, private

def reconstruct(signatures):
    r = b.Z2
    for i, sig in signatures.items():
        sig_point = signature_to_G2(sig)
        coef = 1
        for j in signatures:
            if j != i:
                coef = - coef * (j + 1) * prime_field_inv(i - j, b.curve_order) % b.curve_order
        r = b.add(r, b.multiply(sig_point, coef))
    return G2_to_signature(r)

def get_aggregate_key(keys):
    r = b.Z1
    for i, key in keys.items():
        key_point = pubkey_to_G1(key)
        coef = 1
        for j in keys:
            if j != i:
                coef = - coef * (j + 1) * prime_field_inv(i - j, b.curve_order) % b.curve_order
        r = b.add(r, b.multiply(key_point, coef))
    return G1_to_pubkey(r)

def sign_all(keys, message):
    r = []
    for key in keys:
        r.append(py_ecc_bls.Sign(key, message))
    return r

if __name__ == "__main__":
    aggregate_public, public, private = generate_keys(4, 2)
    signatures = sign_all(private, b"123")
    signature = reconstruct(dict(enumerate(signatures[:-1])))
    assert py_ecc_bls.Verify(aggregate_public, b"123", signature)
    assert aggregate_public == get_aggregate_key(dict(enumerate(public[:-1])))