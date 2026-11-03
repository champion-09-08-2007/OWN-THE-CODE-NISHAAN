# Nishaan

Every printed copy of a question paper is invisibly unique. A photo of any copy (torn, crumpled, serial covered) names the booklet, centre, room and seat. A retyped "guess paper" names the holder it leaked from.

## Run

Needs Python 3.10 or newer.

- Windows: double-click `run.bat`
- macOS / Linux: `./run.sh`

Open http://localhost:8000. The first start takes about 10 seconds while it typesets a demo exam (8 centres, 64 booklets).

To use a phone, scan the QR code on the Trace screen. The phone and laptop must be on the same network. If the venue Wi-Fi blocks devices from seeing each other, connect the laptop to your phone's hotspot. Allow Python through the Windows firewall when asked.

## Before the demo

1. Issue tab: set booklets per centre, click **Issue new run**, open **Print-ready booklets** and print 6 to 10 pages on a laser printer. Any scale works.
2. Photograph a printed page with your phone from the QR page. It should come back **Traced** in a couple of seconds.
3. If real prints come back **Probable** instead of **Traced**, raise the fingerprint strength and reissue:
   - Windows: `set NISHAAN_SHIFT_X=0.45` and `set NISHAAN_SHIFT_Y=0.45` before `run.bat`
   - macOS / Linux: `NISHAAN_SHIFT_X=0.45 NISHAAN_SHIFT_Y=0.45 ./run.sh`

   Keep the same values while tracing. Copies printed with one setting cannot be traced with another.
4. To start clean, stop the app and delete the `var` folder.

## Demo kit

Issue tab, **Demo kit**. It downloads a zip built from your own exam: 6 booklets to print, 3 leak photos (full page, torn piece, crumpled), 2 retyped guess papers, a page that is not this paper, a one-page judge handout, and `PRESENTER-NOTES.txt` listing what each file should trace to. Drag any file onto the Trace screen.

The kit only matches the exam it came from. After a new exam, or a run with a different number of booklets per centre, download it again and reprint.

## Demo script

**Act 1, photo leak (mirrors NEET 2024).** Hand a judge a random printed booklet. Ask them to cover the booklet number with a thumb, tear or crumple it, and photograph it with the phone page. The dashboard jumps to the verdict: booklet number, centre, room, seat, and the custody chain lights up from press to seat. Open **Compare**, blink two booklets: no visible difference. Switch to **Difference** to show the fingerprint.

**Act 2, retyped leak (mirrors NEET 2026).** On Trace, click **Retyped leak** (or paste any leaked text). The verdict names the moderator, translator or centre whose wording it carries, and the chain shows every centre exposed when the leak came before printing.

**Close.** Open **Ledger** and click **Verify again**: every issue, print run and trace is hash-chained.

The **Rehearse** buttons generate synthetic phone photos and retyped leaks, so you can practise without a printer.

## How it works

- **Typographic fingerprint.** Each booklet shifts every word and line by about a third of a point, drawn from a secret per copy. Margins stay straight. The tracer aligns a photo to the master page, measures every word to a fraction of a pixel, removes lens and paper distortion, and correlates what is left against every issued booklet.
- **Canary wording.** Each moderator and translator receives a soft copy with its own meaning-preserving wording and option order. Each centre prints its own option order. A retyped leak keeps those choices.
- **Custody ledger.** Every event is chained with SHA-256, so any edit breaks the chain.

## Optional

- **Telegram bot:** create a bot with @BotFather and set `TELEGRAM_BOT_TOKEN` before starting. Forward a leaked photo or text to the bot and it replies with the source.
- **OCR:** install [Tesseract](https://github.com/tesseract-ocr/tesseract). Screenshots of typed guess papers are then read and traced through the canary wording.
- **Public URL for the phone page:** set `NISHAAN_PUBLIC_URL` (for example a tunnel address) and the QR code uses it.

## Layout

```
app/
  paper.py      question bank, canary slots, holder and centre variants
  typeset.py    deterministic booklet layout and PDF output
  model.py      exam model, reference renders, fingerprint strength
  tracer.py     photo registration, word measurement, copy matching
  canary.py     retyped-leak tracer
  simulate.py   synthetic photos and leaks for rehearsal
  service.py    issuing, tracing, custody resolution
  db.py         SQLite store and hash-chained ledger
  main.py       API, live events, static files
  bot.py        optional Telegram bot
static/         dashboard and phone page
```

Fonts: Archivo and Liberation Serif, both under the SIL Open Font License.
