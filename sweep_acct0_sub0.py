#!/usr/bin/env python3
"""Sweep all unlocked from account 0, subaddress 0 only."""

import requests
import sys
import argparse
from datetime import datetime, timezone

DEST_ADDR = "9zZov316mrm2gNV9jhhEwW5AuBehbC1gG75SkaKLiNT22QqZxTnJd63LwYGP7s24yRfSKyGsyrXzSFyeoT19uj9RM9C9cvB"

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class Sweeper:
    def __init__(self, wallet_url="http://192.168.1.188:28088"):
        self.url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc(self, method, params=None):
        if params is None:
            params = {}
        try:
            r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=120)
            result = r.json()
            if "error" in result and result["error"] is not None:
                return None, f"RPC Error {result['error']['code']}: {result['error']['message']}"
            return result.get("result", {}), None
        except Exception as e:
            return None, str(e)

    def run(self, dest_addr):
        print(f"[{ts()}] Sweeping account 0, subaddr 0 -> {dest_addr}")
        params = {
            "address": dest_addr,
            "account_index": 0,
            "subaddr_indices": [0],
            "priority": 0,
            "get_tx_keys": True,
        }
        result, err = self.rpc("sweep_all", params)
        if err:
            print(f"  FAILED: {err}")
            sys.exit(1)

        hashes = result.get("tx_hash_list", [])
        amounts = result.get("amount_list", [])
        fees = result.get("fee_list", [])
        print(f"  SUCCESS — {len(hashes)} transaction(s)")
        for i, h in enumerate(hashes):
            amt = amounts[i] / 1e12 if i < len(amounts) else 0
            fee = fees[i] / 1e12 if i < len(fees) else 0
            print(f"    TX {i+1}: {h}")
            print(f"      Amount: {amt:.12f}  Fee: {fee:.12f}")
        total_sent = sum(amounts) / 1e12
        total_fee = sum(fees) / 1e12
        print(f"  Total sent: {total_sent:.12f} XMR  Total fee: {total_fee:.12f} XMR")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://192.168.1.188:28088")
    p.add_argument("--dest", default=DEST_ADDR)
    args = p.parse_args()
    try:
        Sweeper(args.wallet_url).run(args.dest)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(0)
