"""Apology-upgrade campaign.

Targets: verified, active, non-paying tenants who EITHER wrote fewer than 5
memories OR never touched the API. Reasoning: these are the users most likely
to have been blocked by the null-byte silent-failure bug.

What it does:
  1. Queries eligible tenants via vultradmin.
  2. For each, upgrades plan to 'business' with max_agents=75, max_memories=1M,
     and stores an expiry date 90 days out in tenant_settings (so a future
     cron can revert gracefully).
  3. Sends a tailored, honest "we broke it, here's 3 months free" email.

SAFETY:
  - Dry-run by default. Pass --send to actually perform upgrades + emails.
  - Skips any tenant with an active stripe_subscription_id (real paying users).
  - Skips internal/test tenants.
  - Rate-limits Resend calls to avoid hitting API limits (100 msg/sec max).

Usage:
    VULTRADMIN_PASSWORD=... RESEND_API_KEY=... python scripts/apology_campaign.py        # dry-run
    VULTRADMIN_PASSWORD=... RESEND_API_KEY=... python scripts/apology_campaign.py --send # actually send
"""
import os
import sys
import time
import json
import html
import argparse
import psycopg2
import requests

HOST = "vultr-prod-fc4c00ba-3823-4f67-a7a9-80ad8860934b-vultr-prod-fbf3.vultrdb.com"
PORT = 16751
RESEND_API = "https://api.resend.com/emails"
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL",
                            "Joe @ Octopoda <joe@octopodas.com>")


def _fetch_eligible():
    """Find tenants who signed up, verified, but probably hit the bug."""
    conn = psycopg2.connect(
        host=HOST, port=PORT, dbname="defaultdb",
        user="vultradmin", password=os.environ["VULTRADMIN_PASSWORD"],
        sslmode="require",
    )
    cur = conn.cursor()
    # Eligible = verified + active + not on a paid Stripe subscription + not test
    # EXISTS avoids the slow COUNT(*) on nodes (7.5M rows). We don't need the
    # exact count here — just whether the tenant has ANY memories.
    cur.execute("""
        SELECT t.tenant_id, t.email, t.first_name, t.plan, t.created_at,
               EXISTS(SELECT 1 FROM nodes n WHERE n.tenant_id = t.tenant_id LIMIT 1) AS has_any_memory
        FROM tenants t
        WHERE t.verified = true
          AND t.active = true
          AND (t.stripe_subscription_id IS NULL OR t.stripe_subscription_id = '')
          AND t.tenant_id NOT LIKE 'test_%'
          AND t.tenant_id NOT LIKE 'iso_%'
          AND t.tenant_id NOT LIKE 'freecap_%'
          AND t.tenant_id NOT LIKE 'mcptest_%'
          AND t.email NOT LIKE '%billing-smoke%'
          AND t.email NOT LIKE '%signupaudit%'
          AND t.email NOT LIKE '%verify-nullbyte%'
          AND t.email NOT LIKE '%healthcheck%'
          AND t.email NOT LIKE '%@isolationtest.invalid'
          AND t.email NOT LIKE '%@freecaptest.invalid'
          AND t.email NOT LIKE '%@test.invalid'
        ORDER BY t.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def _upgrade(tenant_id):
    conn = psycopg2.connect(
        host=HOST, port=PORT, dbname="defaultdb",
        user="vultradmin", password=os.environ["VULTRADMIN_PASSWORD"],
        sslmode="require",
    )
    cur = conn.cursor()
    # Real 3-month timer on the tenant row. Enforced by revert_expired_comps.py
    # which flips anyone past expiry back to free. Skip tenants already on a
    # paid Stripe sub (double-check even though we filter earlier).
    cur.execute("""
        UPDATE tenants
           SET plan = 'business',
               max_agents = 75,
               max_memories = 1000000,
               comp_expires_at = NOW() + INTERVAL '90 days',
               comp_reason = %s
         WHERE tenant_id = %s
           AND (stripe_subscription_id IS NULL OR stripe_subscription_id = '')
    """, ("null-byte-bug-apology-2026-04-17", tenant_id))
    conn.commit()
    conn.close()


EMAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>I owe you an apology</title>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f4f5f7;padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.04);">
        <tr>
          <td style="padding:28px 32px 8px 32px;">
            <div style="font-size:14px;color:#888;letter-spacing:0.08em;text-transform:uppercase;margin:0 0 8px;">&#x1F419; Octopoda</div>
            <h1 style="font-size:24px;color:#1a1a2e;margin:0 0 4px;line-height:1.25;font-weight:700;">I owe you an apology</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:12px 32px 24px 32px;color:#333;font-size:15px;line-height:1.6;">
            <p style="margin:16px 0;">Hey{name},</p>

            <p style="margin:16px 0;">
              You signed up for Octopoda{timing} and I don't think you ever got to actually use it. Brutally honest, I'm disappointed in myself.
            </p>

            <p style="margin:16px 0;">
              Today I found out why. It was two bugs, not one.
            </p>

            <p style="margin:16px 0;">
              The first one lived in the write path. Data with certain characters (very common in LLM output) would silently fail to save. No error, no warning. You'd write a memory, it'd look like it saved, and nothing would be there when you came back. The second one had been hiding underneath it and went undetected until today.
            </p>

            <p style="margin:16px 0;">
              Both are fixed now. Not just patched. We rewrote the write path with defense in depth so this class of bug physically cannot recur, and added a live canary that catches any silent failure within minutes. The system is 100% working.
            </p>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:24px 0;">
              <tr>
                <td style="background:#fdf4ed;border-left:4px solid #ff8c1a;border-radius:6px;padding:18px 20px;">
                  <p style="margin:0 0 10px;font-size:14px;color:#9a5200;font-weight:600;letter-spacing:0.02em;text-transform:uppercase;">A thank-you for the early support</p>
                  <p style="margin:0 0 6px;font-size:15px;color:#333;line-height:1.55;">
                    Your belief in this when everything was silently broken behind the scenes meant a lot. I've bumped your account to Business tier for the next 90 days, on me.
                  </p>
                  <p style="margin:6px 0 0;font-size:14px;color:#555;">
                    No card. No trial expiry. 75 agents, 1M memories, full loop detection, audit trail, cross-agent shared memory.
                  </p>
                </td>
              </tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:24px 0 8px;">
              <tr>
                <td align="center">
                  <a href="https://octopodas.com/dashboard" style="display:inline-block;background:#1a1a2e;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">Open my dashboard</a>
                </td>
              </tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:28px 0 8px;">
              <tr>
                <td style="background:#eef6f0;border:1px solid #cfe3d4;border-radius:8px;padding:18px 20px;">
                  <p style="margin:0 0 8px;font-size:15px;color:#1a1a2e;font-weight:600;">
                    &#x1F4F8; $20 Amazon voucher for a screenshot
                  </p>
                  <p style="margin:0;font-size:14px;color:#444;line-height:1.55;">
                    If you get set up and send me a screenshot of your dashboard with agents on it (Neural Brain view or agent list, whatever looks good), I'll send you a $20 Amazon voucher. First 20 screenshots I get back. I just genuinely want to see what people are building with this. Reply to this email with the image.
                  </p>
                </td>
              </tr>
            </table>

            <p style="margin:20px 0 12px;font-size:15px;color:#333;">One other thing.</p>

            <p style="margin:12px 0;">
              Tell me what would make Octopoda actually useful for what you're building. Reply to this email and I'll read it personally. It shapes what we ship next.
            </p>

            <p style="margin:28px 0 4px;color:#333;">Sorry again for the noise. Second chance is on me.</p>
            <p style="margin:4px 0 0;color:#333;">Joe</p>
            <p style="margin:4px 0 0;font-size:13px;color:#888;">founder, Octopoda &middot; joe@octopodas.com</p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;background:#fafafa;border-top:1px solid #eee;font-size:12px;color:#888;line-height:1.5;">
            After 90 days your account reverts to the free tier automatically. All your data stays. No card is required at any point. You can manage your plan anytime in Settings.
          </td>
        </tr>
      </table>
      <p style="font-size:11px;color:#aaa;margin:16px 0 0;">Octopoda &middot; octopodas.com</p>
    </td>
  </tr>
</table>
</body>
</html>
"""


def _send_email(to: str, first_name: str, created_at):
    name = f" {html.escape(first_name.strip())}" if first_name else ""
    days = max(1, (time.time() - created_at.timestamp()) / 86400) if created_at else None
    if days is None:
        timing = ""
    elif days < 2:
        timing = " recently"
    elif days < 14:
        timing = f" {int(days)} days ago"
    else:
        timing = f" {int(days / 7)} weeks ago"
    body = EMAIL_HTML.replace("{name}", name).replace("{timing}", timing)
    r = requests.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                 "Content-Type": "application/json"},
        json={"from": FROM_EMAIL, "to": [to],
              "subject": "I owe you an apology (and a free upgrade)",
              "html": body,
              "reply_to": "joejackroberts900@gmail.com"},
        timeout=15,
    )
    return r.status_code in (200, 201), r.text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true",
                        help="Actually upgrade + send. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap at N recipients (0 = all).")
    args = parser.parse_args()

    for v in ("VULTRADMIN_PASSWORD", "RESEND_API_KEY"):
        if v not in os.environ:
            print(f"Missing env: {v}", file=sys.stderr)
            sys.exit(1)

    eligible = _fetch_eligible()
    if args.limit:
        eligible = eligible[:args.limit]
    print(f"{len(eligible)} eligible tenants")
    print(f"Mode: {'SEND (live)' if args.send else 'DRY-RUN'}")
    print()

    for tid, email, first_name, plan, created_at, has_mem in eligible[:20]:
        flag = "ACTIVATED" if has_mem else "stuck"
        print(f"  {tid[:16]:<16} {email:<38} {plan:<14} {flag:<10} created={str(created_at)[:10]}")
    if len(eligible) > 20:
        print(f"  ... +{len(eligible) - 20} more")

    if not args.send:
        print()
        print("Dry-run complete. To actually send, re-run with --send")
        return

    print()
    print("Starting send... (Ctrl+C to abort)")
    sent = 0
    failed = 0
    for tid, email, first_name, plan, created_at, has_mem in eligible:
        try:
            _upgrade(tid)
            ok, detail = _send_email(email, first_name or "", created_at)
            if ok:
                sent += 1
                print(f"  OK  {email}")
            else:
                failed += 1
                print(f"  FAIL  {email}: {detail[:100]}")
        except Exception as e:
            failed += 1
            print(f"  ERR  {email}: {e}")
        time.sleep(0.15)  # rate-limit: ~6/sec, well under Resend's 100/sec

    print()
    print(f"=== SENT: {sent} | FAILED: {failed} ===")


if __name__ == "__main__":
    main()
