#!/bin/bash
# Default-deny egress for the Scio devcontainer (issue #5), after Anthropic's reference init-firewall.sh
# (https://github.com/anthropics/claude-code/blob/main/.devcontainer/init-firewall.sh), without the `aggregate`
# dependency and with Scio's own hosts. Run as root (postStartCommand does: sudo .devcontainer/init-firewall.sh).
#
# What stays reachable: DNS (to the configured resolvers), localhost, the host network, GitHub (its published meta ranges: git/api/web),
# scio.md (the wiki - resolved at start; it sits behind Cloudflare, so re-run this script if its IPs rotate),
# api.anthropic.com + statsig/sentry (Claude Code itself), registry.npmjs.org (npx skills), and every domain
# listed in SCIO_FW_ALLOW (space-separated). Everything else is REJECTed.
#
# The honest trade-off: Scio research and blind review open arbitrary web sources (rule 8 - a reviewer reads the
# source, not the snapshot). Under this firewall those fetches fail; the agent can still read the platform's
# archived copies, but independent verification is degraded. For a research/review run either extend
# SCIO_FW_ALLOW with the sources' hosts, or run without the firewall and keep the harness prompts on instead.
set -euo pipefail
IFS=$'\n\t'

SCIO_FW_ALLOW="${SCIO_FW_ALLOW:-}"

# Fail closed: an error before the default-deny below (GitHub meta unreachable, ipset missing, a bad CIDR) must not leave
# the ACCEPT policies of step 1 in place — `set -e` would exit with the container wide open. Until FW_DONE=1 any exit
# turns the policies to DROP (loopback keeps its ACCEPT rules; re-run the script to open the allowlist again).
FW_DONE=0
fail_closed() {
    echo "ERROR: firewall setup did not reach default-deny; closing egress (loopback only) — fix the error above and re-run"
    iptables -P INPUT DROP; iptables -P FORWARD DROP; iptables -P OUTPUT DROP
    command -v ip6tables >/dev/null && { ip6tables -P INPUT DROP; ip6tables -P FORWARD DROP; ip6tables -P OUTPUT DROP; } 2>/dev/null || true
}
trap '[ "$FW_DONE" = 1 ] || fail_closed' EXIT

# 1. Docker's embedded DNS (127.0.0.11) NAT rules must survive the flush
DOCKER_DNS_RULES=$(iptables-save -t nat | grep "127\.0\.0\.11" || true)
# Open up while rebuilding (a re-run starts under the previous run's DROP policy; -F clears rules, not policies —
# without this, the GitHub fetch below is dropped and the script can never be run twice)
iptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT
iptables -F; iptables -X
iptables -t nat -F; iptables -t nat -X
iptables -t mangle -F; iptables -t mangle -X
ipset destroy allowed-domains 2>/dev/null || true
if [ -n "$DOCKER_DNS_RULES" ]; then
    iptables -t nat -N DOCKER_OUTPUT 2>/dev/null || true
    iptables -t nat -N DOCKER_POSTROUTING 2>/dev/null || true
    echo "$DOCKER_DNS_RULES" | xargs -L 1 iptables -t nat
fi

# 2. Loopback, then DNS — to the resolvers this container is configured with, not to any host on port 53 (a DNS
# tunnel to an arbitrary resolver would be an open egress). SSH gets no blanket rule: GitHub's ranges are in the
# allowlist below, any other git host goes into SCIO_FW_ALLOW.
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
RESOLVERS=$(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf 2>/dev/null | grep -E '^[0-9.]+$' || true)
if [ -z "$RESOLVERS" ]; then
    echo "WARN: no IPv4 nameserver in /etc/resolv.conf; allowing DNS to any host"
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
else
    while read -r ns; do
        iptables -A OUTPUT -d "$ns" -p udp --dport 53 -j ACCEPT
        iptables -A OUTPUT -d "$ns" -p tcp --dport 53 -j ACCEPT
    done <<< "$RESOLVERS"
fi
iptables -A INPUT -p udp --sport 53 -m state --state ESTABLISHED -j ACCEPT

ipset create allowed-domains hash:net

# 3. GitHub by its published CIDR ranges (git+api+web move too often for one dig)
echo "Fetching GitHub IP ranges..."
gh_ranges=$(curl -s --connect-timeout 10 https://api.github.com/meta)
if [ -z "$gh_ranges" ] || ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null; then
    echo "ERROR: could not fetch GitHub meta ranges"; exit 1
fi
while read -r cidr; do
    [[ "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]] || { echo "ERROR: bad CIDR from GitHub meta: $cidr"; exit 1; }
    ipset add allowed-domains "$cidr" 2>/dev/null || true   # overlapping ranges are fine without `aggregate`
done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | grep -v ':')

# 4. Named hosts, resolved now. A host that must work fails the script; telemetry that does not resolve is only a
# warning — a failed resolution must never abort BEFORE the default-deny below, or the firewall ends up open.
resolve_into_set() {   # $1 = domain, $2 = required|optional
    echo "Resolving $1..."
    local ips
    ips=$(dig +noall +answer A "$1" | awk '$4 == "A" {print $5}')
    if [ -z "$ips" ]; then
        [ "$2" = required ] && { echo "ERROR: could not resolve $1"; return 1; }
        echo "WARN: could not resolve $1 (optional); skipping"; return 0
    fi
    while read -r ip; do
        [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || { echo "ERROR: bad IP for $1: $ip"; return 1; }
        ipset add allowed-domains "$ip" 2>/dev/null || true
    done <<< "$ips"
}
FW_ERR=0
IFS=' ' read -r -a EXTRA_DOMAINS <<< "$SCIO_FW_ALLOW"   # split on spaces despite the strict IFS above
for domain in scio.md api.anthropic.com registry.npmjs.org ${EXTRA_DOMAINS[@]+"${EXTRA_DOMAINS[@]}"}; do
    resolve_into_set "$domain" required || FW_ERR=1
done
for domain in statsig.anthropic.com statsig.com sentry.io; do
    resolve_into_set "$domain" optional || FW_ERR=1
done

# 4b. IPv6: no allowlist is kept for it, so it is closed outright (an IPv4-only allowlist with open IPv6 is no fence)
if command -v ip6tables >/dev/null; then
    ip6tables -F 2>/dev/null || true
    ip6tables -A INPUT -i lo -j ACCEPT 2>/dev/null || true
    ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
    ip6tables -P INPUT DROP 2>/dev/null || true
    ip6tables -P FORWARD DROP 2>/dev/null || true
    ip6tables -P OUTPUT DROP 2>/dev/null || true
fi

# 5. Host network (the devcontainer gateway), then default-deny
HOST_IP=$(ip route | grep default | cut -d" " -f3)
[ -n "$HOST_IP" ] || { echo "ERROR: no default route"; exit 1; }
HOST_NETWORK=$(echo "$HOST_IP" | sed "s/\.[0-9]*$/.0\/24/")
iptables -A INPUT -s "$HOST_NETWORK" -j ACCEPT
iptables -A OUTPUT -d "$HOST_NETWORK" -j ACCEPT
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT
iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
FW_DONE=1   # default-deny is in force from here: a later error (verification) no longer needs the trap
[ "$FW_ERR" = 0 ] || { echo "ERROR: a required host did not resolve (see above); default-deny IS in force, but the allowlist is incomplete"; exit 1; }

# 6. Verify: a stranger is unreachable, the wiki and GitHub are
echo "Firewall configuration complete; verifying..."
if curl --connect-timeout 5 -s https://example.com >/dev/null 2>&1; then
    echo "ERROR: verification failed - https://example.com is reachable"; exit 1
fi
for must in https://scio.md/v1/stats https://api.github.com/zen; do
    curl --connect-timeout 10 -s "$must" >/dev/null || { echo "ERROR: verification failed - $must is NOT reachable"; exit 1; }
done
echo "Firewall verification passed: example.com blocked; scio.md and api.github.com reachable."
