# vici

A service that receives SMS messages from workers, extracts job preferences via GPT, and returns ranked job listings that help them hit their earnings goal in the shortest possible time.

## Inngest Cloud Setup

Before first production deploy, register the app with Inngest Cloud and obtain two secrets for Render:

### 1. Create an Inngest account and app

1. Sign up at https://app.inngest.com
2. Create a new app (e.g. "vici")

### 2. Obtain INNGEST_SIGNING_KEY

The signing key authenticates requests between Inngest Cloud and your deployed service.

1. In the Inngest Cloud dashboard, open your app
2. Navigate to **Manage -> Signing Key**
3. Copy the signing key value
4. In the Render dashboard, set `INNGEST_SIGNING_KEY` to this value

### 3. Obtain INNGEST_EVENT_KEY

The event key authorizes your app to send events to Inngest Cloud.

1. In the Inngest Cloud dashboard, navigate to **Manage -> Event Keys**
2. Click **Create Event Key**, name it (e.g. "vici-production")
3. Copy the key value
4. In the Render dashboard, set `INNGEST_EVENT_KEY` to this value

### 4. Register your deployed app URL

After first deploy, Inngest Cloud must know your app's function endpoint:

1. In the Inngest Cloud dashboard, navigate to **Apps**
2. Click **Sync new app**
3. Enter your Render service URL: `https://<your-render-service>.onrender.com/api/inngest`
4. Inngest will discover and register all functions (process_message, sync_pinecone_queue)

### Local development

Local dev uses the Inngest Dev Server (no cloud account required):

```bash
npx inngest-cli@latest dev
```

Set `INNGEST_DEV=1` and `INNGEST_BASE_URL=http://localhost:8288` in your `.env`.
