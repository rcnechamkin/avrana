# Welcome to Avrana

> Promoted from the BookStack wiki on 2026-10-04 (page 45, "Welcome to Avrana", last edited 2026-09-10) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: member-facing text.
> Original: [archive](../../docs/archive/bookstack/raw/member-onboarding/45-welcome-to-avrana.md).

Avrana is a small, private media service shared with friends and family. This page gets you set up. You should be able to do all of it yourself: if anything is unclear, see **Getting help** at the bottom.

## 1. Create your Avrana account
You'll receive an **invite link**. Open it and:
1. Pick a **username** and a **password**, and enter your email.
2. Submi: that's it. You now have **one** Avrana account that works across every service you've been given.

> Keep your username and password somewhere safe (a password manager is ideal). You'll use them below.

## 2. Your home page
Go to **https://auth.avrana.net** and sign in. You'll see tiles for **only the services you have access to**: click any tile to open it. This is your Avrana home; bookmark it.

## 3. Signing in to each service
How you sign in depends on the service. Here's each one you might have:

### 🎧 Audiobooks: `listen.avrana.net`
- **Web:** click **Sign in with Avrana** (single sign-on): no separate password.
- **Phone/tablet:** install the **AudioBooth** app (iOS) or the Audiobookshelf app, set the server address to `https://listen.avrana.net`, and choose the single-sign-on / OpenID option.

### 📚 Comics & manga: `read.avrana.net`
Click **Sign in with Avrana** (single sign-on). Works in any browser and in comic reader apps that support OPDS.

### 📖 Books (e-reader library): `books.avrana.net`
This one is slightly differen: on the login page, type your **Avrana username and password** directly (the same ones you created in step 1). Then browse or download EPUBs, or send them to your e-reader.

### 🎬 Movies & TV: `watch.avrana.net`

**On a TV or streaming box, install Wholphin — it's the recommended app.** Wholphin is a Jellyfin app with a cleaner, Netflix-style layout, and it's a nicer experience on the big screen than the standard Jellyfin TV app.
- **Works on Android TV, Google TV, and Fire TV** devices. Get **Wholphin** from the Google Play Store, or from the Amazon Appstore on Fire TV.
- Open it, add the server address `https://watch.avrana.net`, and sign in.
- **Easiest sign-in — Quick Connect:** choose **Quick Connect** in Wholphin and it shows a 6-character code. On your phone, open `https://watch.avrana.net` → profile → **Quick Connect** and enter the code — no typing passwords with a remote. You can also just enter your **Avrana username** and **the password you set at signup**.
- **On a Roku, Apple TV, Samsung, or LG TV** (where Wholphin isn't available), install the standard **Jellyfin** app instead and point it at `https://watch.avrana.net`.

**On a phone, tablet, or computer:** install the **Jellyfin** app, or open `https://watch.avrana.net` in any browser, and sign in with your **Avrana username** and **the password you set at signup**.

> **Important — the one thing that's not automatic:** your Movies & TV password is a **separate copy** made when you signed up. If you later change your main Avrana password, your Movies & TV login keeps the **old** one. Ask an admin if you get stuck here.

### 🍿 Requesting new movies & shows: `request.avrana.net`
Open it and click **Sign in with Jellyfin**: your account is created automatically the first time. Then search for a film or show and request it; it'll appear in Movies & TV once it's added.

### ⬆️ Contributing your own audiobooks: `contribute.avrana.net`
*(Only if you were given contributor access.)* Connect your **Audible** account and pick books you own to add them to the shared audiobook library. You sign in to Amazon on Amazon's own page: **Avrana never sees your Amazon password**. See the on-screen steps; a first connect takes about a minute.

## 4. Forgot your password?
Self-service password reset by email isn't set up yet, so for now **contact an admin** (see below) and they'll reset it for you. *(Admins: this is the pending SMTP/recovery-flow item.)*

## Getting help
Something not working, or you're not sure what you should have access to? **Message the admin who invited you.** Please include which service (the web address) and what you saw.
