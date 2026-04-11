# Domain Setup Runbook

This runbook documents the steps to associate the Squarespace-managed domain with the GKE deployment once the ingress is healthy.

---

## Prerequisites

- Pulumi stack is up (`pulumi up` completed without errors)
- The GKE Ingress is healthy — not in a pending state
- cert-manager issuers are deployed (`letsencrypt-staging` and `letsencrypt-prod` Issuers exist in the `vici` namespace)

---

## 1. Retrieve the Ingress IP

From the `infra/` directory, run:

```
pulumi stack output ingress_external_ip
```

If the output is `PENDING`, the external load balancer has not yet been provisioned. Check ingress status directly:

```
kubectl get ingress vici-ingress -n vici
```

The `ADDRESS` column will be empty until GKE assigns the IP. This can take several minutes after the ingress resource is created.

To confirm the target hostname:

```
pulumi stack output app_hostname
```

This returns the value from `Pulumi.dev.yaml` (e.g., `dev.usevici.com`).

---

## 2. Configure Squarespace DNS

Once you have the IP from step 1:

1. Log in to Squarespace and navigate to **Domains > usevici.com > DNS Settings > Custom Records**.
2. Add an A record with the following values:
   - **Host:** `dev`
   - **Type:** `A`
   - **Data:** the IP address from step 1
   - **TTL:** `300` (5 minutes — lower value aids initial propagation; increase to `3600` once stable)
3. Save the record.

If configuring the apex domain (`usevici.com` for production):

- Add the A record with **Host:** `@` instead of `dev`
- Note: Squarespace does not support CNAME records at the apex; A records are required

---

## 3. Verify DNS Propagation

Run the following commands to confirm propagation:

```
dig dev.usevici.com +short
```

This should return the ingress IP. If it returns nothing or the wrong IP, propagation is still in progress.

Alternatively:

```
nslookup dev.usevici.com
```

Once DNS resolves, verify the app is reachable over HTTPS:

```
curl -I https://dev.usevici.com
```

You may receive a `502 Bad Gateway` initially if app pods are not yet healthy — this is normal. A `200` or `301` indicates the app is reachable.

DNS propagation typically takes 5-30 minutes depending on TTL and resolver caches.

---

## 4. TLS Certificate

The ingress is annotated with `cert-manager.io/issuer: letsencrypt-staging` by default (see `infra/components/ingress.py`). The staging certificate is issued by an untrusted CA — browsers will show a certificate warning, which is expected.

After confirming the staging certificate is issued and ACME HTTP-01 challenges complete successfully:

1. Update the issuer annotation in `infra/components/ingress.py`:

   ```python
   "cert-manager.io/issuer": "letsencrypt-prod",
   ```

2. Apply the change:

   ```
   pulumi up
   ```

3. Delete the existing staging certificate so cert-manager re-issues with the production CA:

   ```
   kubectl delete certificate vici-tls -n vici
   ```

4. Verify the new certificate is issued:

   ```
   kubectl get certificate -n vici
   ```

   The `READY` column should show `True` within a few minutes.

---

## 5. Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `ingress_external_ip` returns `PENDING` | Backend service or pods not ready; GKE load balancer still provisioning | Check `kubectl get pods -n vici` and `kubectl describe ingress vici-ingress -n vici` |
| `502 Bad Gateway` after DNS resolves | App pods crashing or not passing health checks | Check logs: `kubectl logs -n vici -l app=vici-app` |
| Certificate not issued | ACME challenge failing | Check `kubectl describe certificate vici-tls -n vici` and `kubectl get challenges -n vici` |
| DNS not resolving | TTL cache or propagation delay | Wait or flush local DNS: `sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder` (macOS) |
| Staging cert warning in browser | Expected — staging CA is untrusted | Proceed to step 4 to promote to production issuer |
