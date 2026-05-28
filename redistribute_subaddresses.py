#!/usr/bin/env python3
"""
Monero Subaddress Redistribute
Uses account 0, creates 500 subaddresses, then redistributes
balances between them: each funded subaddress splits its unlocked
balance (minus fee reserve) into 16 outputs sent to 16 random
subaddresses via /transfer.
"""

import requests
import json
import sys
import argparse
import random

NUM_DESTINATIONS = 16
TARGET_SUBADDRESSES = 500
FEE_RESERVE = 50000000000

class MoneroSubaddrRedistribute:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc_call(self, method, params=None):
        if params is None:
            params = {}
        payload = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": method,
            "params": params
        }
        try:
            response = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = response.json()
            if "error" in result and result["error"] is not None:
                error = result["error"]
                raise Exception(f"RPC Error {error.get('code', '?')}: {error.get('message', 'Unknown')}")
            return result.get("result", {})
        except Exception as e:
            print(f"    RPC error: {e}")
            return None

    def get_addresses(self, account_index):
        result = self.rpc_call("get_address", {"account_index": account_index})
        if result is None:
            return []
        return result.get("addresses", [])

    def create_addresses(self, account_index, count):
        result = self.rpc_call("create_address", {
            "account_index": account_index,
            "count": count
        })
        if result is None:
            return []
        return result.get("addresses", [])

    def get_balance(self, account_index):
        result = self.rpc_call("get_balance", {"account_index": account_index})
        if result is None:
            return 0, 0, []
        unlocked = result.get("unlocked_balance", 0)
        per_sub = result.get("per_subaddress", [])
        return unlocked, per_sub

    def transfer(self, from_account, subaddr_index, destinations, amount_per_dest):
        dest_list = []
        for addr in destinations:
            dest_list.append({
                "amount": amount_per_dest,
                "address": addr
            })
        params = {
            "destinations": dest_list,
            "account_index": from_account,
            "subaddr_indices": [subaddr_index],
            "priority": 0
        }
        result = self.rpc_call("transfer", params)
        return result

    def format_xmr(self, atomic_units):
        return atomic_units / 1e12

    def run(self):
        print()
        print("=" * 80)
        print("MONERO SUBADDRESS REDISTRIBUTE")
        print("=" * 80)

        # Step 1: Ensure 500 subaddresses exist in account 0
        print("\nChecking subaddresses in account 0...")
        existing = self.get_addresses(0)
        num_existing = len(existing)
        print(f"  Existing subaddresses: {num_existing}")

        if num_existing < TARGET_SUBADDRESSES:
            to_create = TARGET_SUBADDRESSES - num_existing
            print(f"  Creating {to_create} more subaddresses...")
            batch_size = 50
            for i in range(0, to_create, batch_size):
                count = min(batch_size, to_create - i)
                new_addrs = self.create_addresses(0, count)
                if new_addrs:
                    print(f"  Created {i + len(new_addrs)}/{to_create}")
            existing = self.get_addresses(0)
            print(f"  Total subaddresses: {len(existing)}")

        # Build address pool: subaddress_index -> address
        subaddr_map = {}
        for s in existing:
            idx = s.get("address_index")
            addr = s.get("address")
            if idx is not None and addr:
                subaddr_map[idx] = addr

        # Step 2: Get per-subaddress balances
        unlocked_total, per_sub = self.get_balance(0)
        print(f"\n  Total unlocked in account 0: {self.format_xmr(unlocked_total):.12f} XMR")
        print(f"  Subaddresses with balance: {len(per_sub)}")

        # Step 3: Redistribute each funded subaddress
        print(f"\nRedistributing...")
        total_processed = 0
        total_skipped = 0
        total_failed = 0
        total_sent = 0
        total_fees = 0

        for sub in per_sub:
            addr_idx = sub.get("address_index")
            unlocked = sub.get("unlocked_balance", 0)

            if unlocked <= FEE_RESERVE:
                total_skipped += 1
                continue

            # Pick 16 random destination subaddresses (excluding self)
            candidates = [a for i, a in subaddr_map.items() if i != addr_idx]
            if len(candidates) < NUM_DESTINATIONS:
                candidates = list(subaddr_map.values())
            dest_addrs = random.sample(candidates, NUM_DESTINATIONS)

            per_dest = (unlocked - FEE_RESERVE) // NUM_DESTINATIONS
            if per_dest == 0:
                total_skipped += 1
                continue

            print(f"\n  Subaddress {addr_idx}:")
            print(f"    Unlocked: {self.format_xmr(unlocked):.12f} XMR")
            print(f"    Sending {NUM_DESTINATIONS} x {self.format_xmr(per_dest):.12f} XMR")

            result = self.transfer(0, addr_idx, dest_addrs, per_dest)
            if result is None:
                total_failed += 1
                continue

            tx_hash = result.get("tx_hash", "")
            tx_fee = result.get("fee", 0)
            tx_amount = result.get("amount", 0)

            total_processed += 1
            total_sent += tx_amount
            total_fees += tx_fee

            print(f"    Success: Amount: {self.format_xmr(tx_amount):.12f} XMR, Fee: {self.format_xmr(tx_fee):.12f} XMR")
            print(f"      TX: {tx_hash}")

        print(f"\n" + "=" * 80)
        print("REDISTRIBUTION COMPLETE")
        print("=" * 80)
        print(f"  Subaddresses processed: {total_processed}")
        print(f"  Subaddresses failed:    {total_failed}")
        print(f"  Subaddresses skipped:   {total_skipped}")
        print(f"  Total XMR sent:         {self.format_xmr(total_sent):.12f}")
        print(f"  Total fees paid:        {self.format_xmr(total_fees):.12f}")
        print("=" * 80 + "\n")

        return True

def main():
    parser = argparse.ArgumentParser(
        description="Redistribute subaddress balances in account 0 by splitting into 16 outputs to random subaddresses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 redistribute_subaddresses.py
  python3 redistribute_subaddresses.py --wallet-url http://localhost:28088
        """
    )
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    args = parser.parse_args()

    redist = MoneroSubaddrRedistribute(args.wallet_url)
    success = redist.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
