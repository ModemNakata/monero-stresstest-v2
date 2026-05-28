#!/usr/bin/env python3
"""
Monero Redistribute Loop
Runs in an infinite loop with 1-minute delay, performing two phases each iteration:
  Phase 1: Redistribute between subaddresses of account 0 (like redistribute_subaddresses.py)
  Phase 2: Redistribute between primary addresses of all accounts (like redistribute_accounts.py)
Logs everything, never halts on failure.
"""

import requests
import json
import sys
import argparse
import random
import time
from datetime import datetime, timezone

NUM_DESTINATIONS = 16
TARGET_SUBADDRESSES = 500
TARGET_ACCOUNTS = 500
FEE_RESERVE_SUBADDR = 50000000000
FEE_RESERVE_ACCOUNT = 5000000000
INITIAL_FEE_RESERVE = 1000000000
FEE_STEP = 5000000000

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class MoneroRedistributeLoop:
    def __init__(self, wallet_url):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc_call(self, method, params=None):
        if params is None:
            params = {}
        payload = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
        try:
            resp = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = resp.json()
            if "error" in result and result["error"] is not None:
                raise Exception(f"RPC Error {result['error']['code']}: {result['error']['message']}")
            return result.get("result", {})
        except Exception as e:
            return None

    def rpc_call_raw(self, method, params=None):
        if params is None:
            params = {}
        payload = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
        try:
            resp = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = resp.json()
            if "error" in result and result["error"] is not None:
                err = result["error"]
                return f"RPC Error {err.get('code', '?')}: {err.get('message', 'Unknown')}", None
            return None, result.get("result", {})
        except Exception as e:
            return str(e), None

    def format_xmr(self, a):
        return a / 1e12

    # ---- subaddress phase helpers ----

    def get_addresses(self, account_index):
        r = self.rpc_call("get_address", {"account_index": account_index})
        if r is None:
            return []
        return r.get("addresses", [])

    def create_addresses(self, account_index, count):
        r = self.rpc_call("create_address", {"account_index": account_index, "count": count})
        if r is None:
            return []
        return r.get("addresses", [])

    def get_sub_balance(self):
        r = self.rpc_call("get_balance", {"account_index": 0})
        if r is None:
            return 0, []
        return r.get("unlocked_balance", 0), r.get("per_subaddress", [])

    def transfer_sub(self, subaddr_index, destinations, amount_per_dest):
        dest_list = [{"amount": amount_per_dest, "address": a} for a in destinations]
        return self.rpc_call("transfer", {
            "destinations": dest_list,
            "account_index": 0,
            "subaddr_indices": [subaddr_index],
            "priority": 0
        })

    # ---- account phase helpers ----

    def get_accounts(self):
        r = self.rpc_call("get_accounts", {})
        if r is None:
            return []
        return r.get("subaddress_accounts", [])

    def get_account_balance(self, account_index):
        r = self.rpc_call("get_balance", {"account_index": account_index})
        if r is None:
            return 0, 0, 0, []
        return (r.get("balance", 0), r.get("unlocked_balance", 0),
                r.get("blocks_to_unlock", 0), r.get("per_subaddress", []))

    def get_address(self, account_index):
        r = self.rpc_call("get_address", {"account_index": account_index})
        if r is None:
            return None
        return r.get("address", None)

    def create_account(self, label=""):
        params = {"label": label} if label else {}
        r = self.rpc_call("create_account", params)
        if r is None:
            return None
        return r.get("account_index", None)

    def transfer_account(self, from_account, destinations, amount_per_dest, subaddr_indices=None):
        dest_list = [{"amount": amount_per_dest, "address": a} for a in destinations]
        params = {"destinations": dest_list, "account_index": from_account, "priority": 0}
        if subaddr_indices is not None:
            params["subaddr_indices"] = subaddr_indices
        err, result = self.rpc_call_raw("transfer_split", params)
        return err, result

    # ---- phase implementations ----

    def phase_subaddresses(self):
        log = []
        log.append(f"[{ts()}]  --- Phase 1: Subaddress Redistribution ---")

        existing = self.get_addresses(0)
        num_existing = len(existing)
        log.append(f"  Subaddresses in account 0: {num_existing}")

        if num_existing < TARGET_SUBADDRESSES:
            to_create = TARGET_SUBADDRESSES - num_existing
            log.append(f"  Creating {to_create} more...")
            for i in range(0, to_create, 50):
                count = min(50, to_create - i)
                new_addrs = self.create_addresses(0, count)
                if new_addrs:
                    log.append(f"  Created {i + len(new_addrs)}/{to_create}")
            existing = self.get_addresses(0)
            log.append(f"  Total subaddresses: {len(existing)}")

        subaddr_map = {}
        for s in existing:
            idx, addr = s.get("address_index"), s.get("address")
            if idx is not None and addr:
                subaddr_map[idx] = addr

        unlocked_total, per_sub = self.get_sub_balance()
        log.append(f"  Total unlocked: {self.format_xmr(unlocked_total):.12f} XMR")
        log.append(f"  Subaddresses with balance: {len(per_sub)}")

        processed = skipped = failed = 0
        total_sent = total_fees = 0

        for sub in per_sub:
            addr_idx = sub.get("address_index")
            unlocked = sub.get("unlocked_balance", 0)

            if unlocked <= FEE_RESERVE_SUBADDR:
                skipped += 1
                continue

            candidates = [a for i, a in subaddr_map.items() if i != addr_idx]
            if len(candidates) < NUM_DESTINATIONS:
                candidates = list(subaddr_map.values())
            dest_addrs = random.sample(candidates, NUM_DESTINATIONS)

            per_dest = (unlocked - FEE_RESERVE_SUBADDR) // NUM_DESTINATIONS
            if per_dest == 0:
                skipped += 1
                continue

            log.append(f"  Sub {addr_idx}: unlocked={self.format_xmr(unlocked):.12f}, "
                       f"sending {NUM_DESTINATIONS}x{self.format_xmr(per_dest):.12f}")

            result = self.transfer_sub(addr_idx, dest_addrs, per_dest)
            if result is None:
                log.append(f"    FAILED")
                failed += 1
                continue

            tx_hash = result.get("tx_hash", "")
            fee = result.get("fee", 0)
            amount = result.get("amount", 0)
            processed += 1
            total_sent += amount
            total_fees += fee
            log.append(f"    OK: amount={self.format_xmr(amount):.12f}, fee={self.format_xmr(fee):.12f}, tx={tx_hash}")

        log.append(f"  Result: processed={processed}, failed={failed}, skipped={skipped}, "
                   f"sent={self.format_xmr(total_sent):.12f}, fees={self.format_xmr(total_fees):.12f}")
        return log

    def phase_accounts(self):
        log = []
        log.append(f"[{ts()}]  --- Phase 2: Account Redistribution ---")

        accounts = self.get_accounts()
        if not accounts:
            log.append("  No accounts found!")
            return log

        log.append(f"  Existing accounts: {len(accounts)}")

        if len(accounts) < TARGET_ACCOUNTS:
            to_create = TARGET_ACCOUNTS - len(accounts)
            log.append(f"  Creating {to_create} more...")
            for i in range(to_create):
                idx = self.create_account(f"pool-account-{len(accounts) + i}")
                if idx is not None and (i + 1) % 50 == 0:
                    log.append(f"  Created {i + 1}/{to_create}")
            accounts = self.get_accounts()
            log.append(f"  Total accounts: {len(accounts)}")

        account_addresses = {}
        for acc in accounts:
            idx, addr = acc.get("account_index"), acc.get("base_address")
            if idx is not None and addr:
                account_addresses[idx] = addr

        processed = skipped = failed = 0
        total_sent = total_fees = 0

        for acc in accounts:
            account_index = acc.get("account_index")
            label = acc.get("label", "")

            balance, unlocked, blocks_to_unlock, per_sub = self.get_account_balance(account_index)
            if unlocked == 0:
                skipped += 1
                continue

            subaddr_indices = [s["address_index"] for s in per_sub if s.get("unlocked_balance", 0) > 0]
            if not subaddr_indices:
                skipped += 1
                continue

            candidates = [i for i in account_addresses if i != account_index]
            if len(candidates) < NUM_DESTINATIONS:
                candidates = list(account_addresses.keys())
            chosen = random.sample(candidates, NUM_DESTINATIONS)
            dest_addrs = [account_addresses[i] for i in chosen]

            # Retry loop: increase fee reserve on -16 error
            fee_reserve = INITIAL_FEE_RESERVE
            success = False
            result = None
            last_error = None

            while True:
                if unlocked <= fee_reserve:
                    break

                per_dest = (unlocked - fee_reserve) // NUM_DESTINATIONS
                if per_dest == 0:
                    break

                log.append(f"  Acc {account_index} ({label}): unlocked={self.format_xmr(unlocked):.12f}, "
                           f"reserve={self.format_xmr(fee_reserve):.12f}, "
                           f"splitting {NUM_DESTINATIONS}x{self.format_xmr(per_dest):.12f}, "
                           f"blocks_to_unlock={blocks_to_unlock}")

                err, result = self.transfer_account(account_index, dest_addrs, per_dest, subaddr_indices)
                if err is None:
                    success = True
                    break

                last_error = err
                log.append(f"    Failed: {err}")
                log.append(f"    Increasing reserve by {self.format_xmr(FEE_STEP):.12f}...")
                fee_reserve += FEE_STEP

            if not success:
                log.append(f"    Gave up. Last error: {last_error}")
                failed += 1
                continue

            tx_hashes = result.get("tx_hash_list", [])
            fees = result.get("fee_list", [])
            amounts = result.get("amount_list", [])
            tx_fee = sum(fees)
            tx_amount = sum(amounts)
            processed += 1
            total_sent += tx_amount
            total_fees += tx_fee
            log.append(f"    OK (reserve={self.format_xmr(fee_reserve):.12f}): "
                       f"{len(tx_hashes)} tx(s), amount={self.format_xmr(tx_amount):.12f}, "
                       f"fee={self.format_xmr(tx_fee):.12f}")
            for h in tx_hashes:
                log.append(f"      tx={h}")

        log.append(f"  Result: processed={processed}, failed={failed}, skipped={skipped}, "
                   f"sent={self.format_xmr(total_sent):.12f}, fees={self.format_xmr(total_fees):.12f}")
        return log

    def run(self, delay_seconds=60):
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*80}")
            print(f"Iteration {iteration} — {ts()}")
            print(f"{'='*80}")

            # Phase 1: subaddresses
            try:
                for line in self.phase_subaddresses():
                    print(line)
            except Exception as e:
                print(f"  [ERROR] Phase 1 exception: {e}")

            # Phase 2: accounts
            try:
                for line in self.phase_accounts():
                    print(line)
            except Exception as e:
                print(f"  [ERROR] Phase 2 exception: {e}")

            print(f"Iteration {iteration} complete — {ts()}")
            print(f"Sleeping {delay_seconds}s...")
            time.sleep(delay_seconds)


def main():
    parser = argparse.ArgumentParser(
        description="Infinite loop: redistribute subaddresses then accounts every N seconds")
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088")
    parser.add_argument("--delay", type=int, default=60, help="Delay between iterations (seconds)")
    args = parser.parse_args()

    loop = MoneroRedistributeLoop(args.wallet_url)
    try:
        loop.run(delay_seconds=args.delay)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted, exiting.")
        sys.exit(0)

if __name__ == "__main__":
    main()
