# Private CAS importer on OCI Compute

This setup runs the CDSL CAS importer in your own Oracle Cloud account. MFHelper source code comes from the public repository; the holdings snapshot and credentials stay in your OCI tenancy. No private GitHub repository is needed for the importer.

## What it stores

- OCI Object Storage bucket: one object at `holdings/current.json` containing only the latest validated holdings snapshot.
- The bucket must have **Public access: No public access** and **Object versioning: Disabled**.
- The PDF and PAN are held only while the request is processed. Multipart handling may spool the PDF to the VM's private temporary directory; the app closes and deletes that temporary file on success and failure. The PDF/password are not placed in logs or the persistent checkout.
- The GitHub OAuth token is used only to identify the account and is not saved. The server keeps a signed, secure browser session for up to one hour.

The snapshot is not currently read by the daily GitHub Actions workflow or public dashboard.

## OCI resources to create

The VM and storage may fit OCI Always Free limits if eligible resources are available in your tenancy's home region. Verify the console labels and estimated cost before provisioning; Always Free compute capacity can be temporarily unavailable. See [Oracle's current Always Free resource list](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

1. Create an OCI tenancy and choose its home region. Create a compartment for this worker.
2. Create a private Object Storage bucket in the compartment. Turn object versioning off. Do not create any public access links.
3. Create an Ubuntu 24.04 Compute VM in the same region. Add an SSH public key. Assign a **reserved public IPv4 address** so the IP remains stable across VM restarts.
4. In the VM subnet/security list, allow inbound TCP 80 and 443 from the internet. Restrict SSH (TCP 22) to your own current IP where possible. Do not open port 8765.
5. Create a dynamic group with a matching rule for only this VM:

   ```text
   ALL {instance.id = '<VM_INSTANCE_OCID>'}
   ```

6. Add these policies in the bucket's compartment, replacing the group, compartment, and bucket names:

   ```text
   Allow dynamic-group MFHelperHoldingsVM to read buckets in compartment MFHelper where target.bucket.name = 'mfhelper-holdings'
   Allow dynamic-group MFHelperHoldingsVM to manage objects in compartment MFHelper where target.bucket.name = 'mfhelper-holdings'
   ```

   This lets the VM verify the bucket and read/write/delete its snapshot through an OCI instance principal. Do not put an OCI API signing key on the VM.

7. In GitHub, create an OAuth App for sign-in only. Set its callback URL to `https://<RESERVED_PUBLIC_IP>/oauth/callback`. Keep the client secret for the VM setup. MFHelper requests only the `read:user` scope and accepts only the configured GitHub login.

## Install on the VM

SSH to the VM and run the following as your normal login user:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv python3-dev build-essential nginx
sudo adduser --system --group --home /opt/mfhelper mfhelper
sudo git clone https://github.com/Pratikphukan/mfhelper.git /opt/mfhelper/app
sudo chown -R mfhelper:mfhelper /opt/mfhelper/app
sudo -u mfhelper python3 -m venv /opt/mfhelper/venv
sudo -u mfhelper /opt/mfhelper/venv/bin/pip install -r /opt/mfhelper/app/requirements-oci.txt
```

Create `/etc/mfhelper-holdings.env` as root with mode `0600`:

```text
MFHELPER_PUBLIC_URL=https://<RESERVED_PUBLIC_IP>
MFHELPER_SESSION_SECRET=<random-secret-at-least-32-characters>
GITHUB_OAUTH_CLIENT_ID=<oauth-client-id>
GITHUB_OAUTH_CLIENT_SECRET=<oauth-client-secret>
GITHUB_ALLOWED_LOGIN=<your-github-login>
OCI_REGION=<your-home-region>
OCI_NAMESPACE=<your-object-storage-namespace>
OCI_BUCKET_NAME=mfhelper-holdings
```

Generate the session secret with `openssl rand -hex 32`. Get the namespace from OCI Object Storage details. Do not put these values in the public MFHelper checkout.

Install `deploy/oci-vm/mfhelper-holdings.service` as `/etc/systemd/system/mfhelper-holdings.service`, then run:

```bash
sudo chmod 600 /etc/mfhelper-holdings.env
sudo systemctl daemon-reload
sudo systemctl enable --now mfhelper-holdings
```

The systemd unit disables Uvicorn access logs so OAuth callback codes are not written to the journal. The Nginx configuration below disables request access logs as well.

## HTTPS for a public IP

Let's Encrypt now issues IP-address certificates. They are valid for about 160 hours, so automatic renewal is required. Certbot 5.4 or newer supports requesting them. The IP must be stable and ports 80/443 must reach the VM.

1. Install Certbot 5.4+ in an isolated environment (for example, a venv at `/opt/certbot`):

   ```bash
   sudo python3 -m venv /opt/certbot
   sudo /opt/certbot/bin/pip install 'certbot>=5.4,<6'
   ```

2. Install `deploy/oci-vm/nginx-http.conf` as `/etc/nginx/sites-available/mfhelper-holdings` and enable it. This serves the ACME challenge directory over port 80 and redirects other requests to HTTPS.
3. Create the challenge directory and start Nginx:

   ```bash
   sudo mkdir -p /var/www/letsencrypt
   sudo nginx -t && sudo systemctl enable --now nginx
   ```

4. Request a staging IP certificate first (replace `<CERTBOT>` with the path to Certbot 5.4+ and `<IP>` with the reserved IP):

   ```bash
   sudo <CERTBOT> certonly --staging --preferred-profile shortlived --webroot \
     --webroot-path /var/www/letsencrypt --ip-address <IP>
   ```

   After confirming the challenge succeeds, repeat without `--staging` to receive the browser-trusted certificate.
5. Install `deploy/oci-vm/nginx-https.conf` with `<IP>` replaced. Validate and reload Nginx. This proxy listens on 443 and forwards to the app on loopback only.
6. Install `deploy/oci-vm/certbot-renew.service` and `deploy/oci-vm/certbot-renew.timer` under `/etc/systemd/system/`, then enable the timer. The renewal service reloads Nginx after a certificate is renewed.

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now certbot-renew.timer
   systemctl list-timers certbot-renew.timer
   ```

Let’s Encrypt’s IP certificates are short-lived. Check the timer and renewal logs after setup and periodically confirm renewals succeed; an expired certificate will block browser access and GitHub OAuth.

## Use and update

Open `https://<RESERVED_PUBLIC_IP>/`, sign in with the allowed GitHub account, choose the CDSL PDF, and enter the PAN password. The importer writes the latest snapshot to `holdings/current.json` only after a complete successful parse. A repeated statement is reported as already imported; older statements cannot replace a newer snapshot.

To update the public code, pull the intended public branch in `/opt/mfhelper/app` and restart `mfhelper-holdings`. Keep `/etc/mfhelper-holdings.env` outside the checkout. Stop the VM when you do not need the import page if you want to reduce compute use; re-check the reserved IP and HTTPS certificate renewal behavior before restarting it.

## References

- [OCI resource principals for Compute](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm)
- [OCI Object Storage policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm)
- [Let's Encrypt IP certificates and six-day certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Certbot IP certificate setup](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)
