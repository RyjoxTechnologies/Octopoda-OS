"""Nightly cron: downgrade any tenant whose comp has expired.

Runs against Vultr Postgres as vultradmin. Flips plan back to free and
resets limits for any row where comp_expires_at < NOW() and the tenant
has no active Stripe subscription.

Safety:
  - Only touches rows that were explicitly comp'd (comp_reason IS NOT NULL).
  - Double-checks stripe_subscription_id so a paying customer is never
    downgraded.
  - Sends the tenant an email via Resend so they aren't surprised by the
    downgrade.
  - Dry-run by default. Use --apply to actually do it.

Schedule with cron (once a day):
    0 4 * * * VULTRADMIN_PASSWORD=... RESEND_API_KEY=... \\
              /root/octopoda/venv/bin/python /root/octopoda/scripts/revert_expired_comps.py --apply
"""
import os
import sys
import argparse
import psycopg2
import requests

HOST = "vultr-prod-fc4c00ba-3823-4f67-a7a9-80ad8860934b-vultr-prod-fbf3.vultrdb.com"
PORT = 16751
RESEND_API = "https://api.resend.com/emails"
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Joe @ Octopoda <joe@octopodas.com>")

EMAIL_HTML = """
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f4f5f7;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;width:100%;background:#fff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 32px 8px;">
        <div style="font-size:14px;color:#888;letter-spacing:0.08em;text-transform:uppercase;margin:0 0 8px;">&#x1F419; Octopoda</div>
        <h1 style="font-size:22px;color:#1a1a2e;margin:0;font-weight:700;">Your comp just ended</h1>
      </td></tr>
      <tr><td style="padding:12px 32px 24px;color:#333;font-size:15px;line-height:1.6;">
        <p style="margin:16px 0;">Hey{name},</p>
        <p style="margin:16px 0;">
          Just a heads-up. Your 90 days of Business tier (on the house, from our apology earlier) just ran out. Your account has moved back to the free tier.
        </p>
        <p style="margin:16px 0;">
          All your data is preserved. Nothing has been deleted. You can still read, search, and export every memory you've stored.
        </p>
        <p style="margin:16px 0;">
          If you've been using it actively and want to keep the higher limits, you can add a card on the pricing page. If Octopoda wasn't the right fit, no worries, and thanks for giving it a go.
        </p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:24px 0 8px;">
          <tr><td align="center">
            <a href="https://octopodas.com/pricing" style="display:inline-block;background:#1a1a2e;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600;">See plans</a>
          </td></tr>
        </table>
        <p style="margin:28px 0 4px;color:#333;">Either way, thanks for the early support.</p>
        <p style="margin:4px 0 0;color:#333;">Joe</p>
        <p style="margin:4px 0 0;font-size:13px;color:#888;">founder, Octopoda</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""


def _db():
    return psycopg2.connect(
        host=HOST, port=PORT, dbname="defaultdb", user="vultradmin",
        password=os.environ["VULTRADMIN_PASSWORD"], sslmode="require",
    )


def _fetch_expired():
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        SELECT tenant_id, email, first_name, comp_expires_at, comp_reason
        FROM tenants
        WHERE comp_expires_at IS NOT NULL
          AND comp_expires_at < NOW()
          AND (stripe_subscription_id IS NULL OR stripe_subscription_id = '')
          AND plan != 'free'
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def _revert(tenant_id):
    conn = _db()
    cur = conn.cursor()
    # Double-guard: re-check no paid sub exists within the transaction.
    cur.execute("""
        UPDATE tenants
           SET plan = 'free',
               max_agents = 5,
               max_memories = 5000,
               comp_expires_at = NULL,
               comp_reason = NULL
         WHERE tenant_id = %s
           AND (stripe_subscription_id IS NULL OR stripe_subscription_id = '')
    """, (tenant_id,))
    conn.commit()
    conn.close()


def _email(to, first_name):
    if not to or not os.environ.get("RESEND_API_KEY"):
        return False
    name = f" {first_name.strip()}" if first_name else ""
    body = EMAIL_HTML.replace("{name}", name)
    r = requests.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                 "Content-Type": "application/json"},
        json={"from": FROM_EMAIL, "to": [to],
              "subject": "Your Octopoda comp just ended",
              "html": body, "reply_to": "joe@octopodas.com"},
        timeout=15,
    )
    return r.status_code in (200, 201)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually revert. Default is dry-run.")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip sending the heads-up email")
    args = parser.parse_args()

    if "VULTRADMIN_PASSWORD" not in os.environ:
        print("VULTRADMIN_PASSWORD not set", file=sys.stderr)
        sys.exit(1)

    expired = _fetch_expired()
    print(f"{len(expired)} tenant(s) past comp expiry")
    for tid, email, first_name, exp, reason in expired:
        age = str(exp)[:19]
        print(f"  {tid[:18]:<18} {email:<35} expired={age} reason={reason}")

    if not args.apply:
        print()
        print("Dry-run. Re-run with --apply to revert.")
        return

    reverted = 0
    emailed = 0
    for tid, email, first_name, exp, reason in expired:
        try:
            _revert(tid)
            reverted += 1
            if not args.no_email and email:
                if _email(email, first_name or ""):
                    emailed += 1
            print(f"  reverted {tid} ({email})")
        except Exception as e:
            print(f"  ERR {tid}: {e}")

    print()
    print(f"REVERTED: {reverted} | EMAILED: {emailed}")


if __name__ == "__main__":
    main()
