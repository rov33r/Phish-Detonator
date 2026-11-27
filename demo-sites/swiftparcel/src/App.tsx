import { useState, type FormEvent, type ReactNode } from "react";

type JourneyStep = "landing" | "tracking" | "verification";

function BoxMark({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <path d="m18 3 14 7.5v15L18 33 4 25.5v-15L18 3Z" stroke="currentColor" strokeWidth="2" />
      <path d="m4.7 10.8 13.3 7.4 13.3-7.4M18 18.2V32M11 7l14 7.7v7" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

function ArrowIcon({ className = "" }: { className?: string }) {
  return <svg className={className} viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3.5 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function BackIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M16 10H4m5 5-5-5 5-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function PinIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" stroke="currentColor" strokeWidth="1.7"/><circle cx="12" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.7"/></svg>;
}

function CheckIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4 10.5 4 4 8-9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}

function Header({ onReset }: { onReset: () => void }) {
  return (
    <header className="site-header">
      <div className="header-inner">
        <a className="brand" href="#top" onClick={onReset} aria-label="SwiftParcel home">
          <BoxMark className="brand-mark" />
          <span>swift<span>parcel</span></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a href="#tracking">Track a parcel</a>
          <a href="#how-it-works">How it works</a>
          <a href="#help">Help centre</a>
        </nav>
        <a className="account-link" href="#help">Need help? <span>Contact us</span></a>
      </div>
    </header>
  );
}

function StepIndicator({ active }: { active: 1 | 2 | 3 }) {
  const items = ["Tracking", "Delivery", "Complete"];
  return (
    <ol className="step-indicator" aria-label="Delivery journey">
      {items.map((item, index) => {
        const number = index + 1;
        const complete = number < active;
        return <li className={number === active ? "current" : complete ? "complete" : ""} key={item} aria-current={number === active ? "step" : undefined}>
          <span className="step-dot">{complete ? <CheckIcon /> : number}</span><span>{item}</span>
        </li>;
      })}
    </ol>
  );
}

function RouteArtwork() {
  return (
    <div className="route-art" aria-label="Illustrated route from our depot to your door" role="img">
      <div className="art-topline"><span>ON ITS WAY</span><span className="art-live"><i /> LIVE ROUTE</span></div>
      <svg className="route-lines" viewBox="0 0 500 350" fill="none" aria-hidden="true">
        <path d="M-5 280c73-41 104-33 144-96 37-58 81-67 126-18 43 47 61 62 125 35 49-21 83-12 126 29" stroke="#91ab96" strokeWidth="1.4" strokeDasharray="4 8" />
        <path d="M-20 118c90 56 114 13 192 41 64 23 90 83 150 69 60-15 112-86 196-44" stroke="#d9e5d8" strokeWidth="1" />
        <path d="M21 318c67-76 90-88 131-82 46 7 67 56 119 42 45-13 55-74 104-93 43-17 79 7 111 22" stroke="#d9e5d8" strokeWidth="1" />
        <circle cx="139" cy="185" r="7" fill="#f3b44e" stroke="#173f38" strokeWidth="4" />
        <circle cx="390" cy="201" r="8" fill="#f3b44e" stroke="#173f38" strokeWidth="4" />
      </svg>
      <div className="art-destination"><PinIcon /><span>YOUR DOOR</span></div>
      <div className="parcel-illustration" aria-hidden="true">
        <div className="parcel-tape" />
        <div className="parcel-face"><span>SP</span><i /></div>
        <div className="parcel-side" />
        <div className="parcel-top" />
      </div>
      <div className="art-caption"><span>From our local depot</span><strong>Out for delivery</strong></div>
      <div className="art-stamp" aria-hidden="true"><BoxMark /><span>GOOD<br/>THINGS<br/>ON THE<br/>WAY</span></div>
      <div className="art-road-label">STOCKHOLM · SE</div>
    </div>
  );
}

function Landing({ trackingCode, setTrackingCode, onTrack }: {
  trackingCode: string;
  setTrackingCode: (value: string) => void;
  onTrack: () => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onTrack();
  }

  return <>
    <main id="top" className="page-shell">
      <section className="hero-grid" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow"><span /> A little closer, every day</p>
          <h1 id="hero-title">Good things<br />are on their way.</h1>
          <p className="hero-intro">A parcel can make an ordinary day feel special. Follow yours from our depot to your doorstep.</p>
          <form className="tracking-form" id="tracking" onSubmit={submit}>
            <label htmlFor="tracking-code">Your tracking number</label>
            <div className="tracking-input-row">
              <input id="tracking-code" value={trackingCode} onChange={(event) => setTrackingCode(event.target.value)} spellCheck={false} autoComplete="off" />
              <button className="button button-dark" type="submit">Track my parcel <ArrowIcon /></button>
            </div>
            <p className="form-hint"><span className="lock-icon" aria-hidden="true">✓</span> Your parcel details are ready to view</p>
          </form>
          <div className="delivery-note">
            <span className="note-symbol" aria-hidden="true"><PinIcon /></span>
            <div><strong>A delivery note for you</strong><p>Choose a safe place or confirm someone will be home.</p></div>
            <button type="button" className="text-button" onClick={onTrack}>Review options <ArrowIcon /></button>
          </div>
        </div>
        <RouteArtwork />
      </section>

      <section className="shipment-strip" aria-label="Current package status">
        <div className="shipment-id"><span className="parcel-icon"><BoxMark /></span><div><span>YOUR PARCEL</span><strong>{trackingCode || "SP-2048-7721"}</strong></div></div>
        <div className="shipment-status"><span className="status-indicator" /><div><span>Current status</span><strong>Out for delivery</strong></div></div>
        <div className="shipment-eta"><span>ESTIMATED DELIVERY</span><strong>Today, 14:00 – 18:00</strong></div>
        <div className="shipment-progress" aria-label="3 of 4 delivery steps complete"><span>3</span><i><b /></i><span>4</span></div>
      </section>

      <section className="service-row" id="how-it-works">
        <p>Thoughtful delivery, from start to finish.</p>
        <div><span className="service-mark">01</span> Carefully handled</div>
        <div><span className="service-mark">02</span> Tracked at every step</div>
        <div><span className="service-mark">03</span> Delivered with care</div>
      </section>
    </main>
    <Footer />
  </>;
}

function Tracking({ trackingCode, onContinue, onBack }: { trackingCode: string; onContinue: () => void; onBack: () => void }) {
  return <main className="journey-shell">
    <button className="back-button" onClick={onBack} type="button"><BackIcon /> Back to tracking</button>
    <StepIndicator active={2} />
    <section className="journey-heading">
      <p className="eyebrow"><span /> DELIVERY UPDATE</p>
      <h1>Your parcel is almost there.</h1>
      <p>We have your parcel at the local depot and are preparing the final delivery.</p>
    </section>
    <section className="journey-layout">
      <div className="journey-main">
        <div className="journey-status">
          <div className="status-check"><CheckIcon /></div>
          <div><span>ON THE WAY · {trackingCode}</span><h2>Out for delivery</h2><p>Our driver is making their rounds in your area.</p></div>
          <strong className="eta-chip">Today</strong>
        </div>
        <div className="delivery-address">
          <span className="address-icon"><PinIcon /></span>
          <div><span>DELIVERING TO</span><strong>Stockholm, Sweden</strong><p>Address details confirmed with sender</p></div>
          <span className="address-check"><CheckIcon /></span>
        </div>
        <div className="timeline-card">
          <h2>Parcel journey</h2>
          <ol className="parcel-timeline">
            <li className="done"><span><CheckIcon /></span><div><strong>Parcel collected</strong><small>Yesterday · 16:42</small></div></li>
            <li className="done"><span><CheckIcon /></span><div><strong>Arrived at local depot</strong><small>Today · 07:18</small></div></li>
            <li className="active"><span><i /></span><div><strong>Out for delivery</strong><small>Today · 09:06</small></div></li>
          </ol>
        </div>
      </div>
      <aside className="continue-panel">
        <span className="continue-icon"><PinIcon /></span>
        <p className="eyebrow"><span /> ONE MORE STEP</p>
        <h2>Let’s make sure we find you.</h2>
        <p>Confirm your delivery details so your parcel doesn’t have to make a second trip.</p>
        <button className="button button-dark button-wide" type="button" onClick={onContinue}>Continue to delivery <ArrowIcon /></button>
        <small>Usually takes less than a minute</small>
      </aside>
    </section>
    <Footer />
  </main>;
}

function MockField({ label, placeholder, type = "text", adornment }: { label: string; placeholder: string; type?: string; adornment?: ReactNode }) {
  return <label className="mock-field"><span>{label}</span><span className="mock-input-wrap"><input type={type} placeholder={placeholder} readOnly aria-readonly="true" autoComplete="off" tabIndex={-1} />{adornment && <i>{adornment}</i>}</span></label>;
}

function Verification({ onBack }: { onBack: () => void }) {
  const [notice, setNotice] = useState(false);
  return <main className="verification-shell">
    <button className="back-button" onClick={onBack} type="button"><BackIcon /> Back to delivery</button>
    <StepIndicator active={3} />
    <div className="verification-heading">
      <div><p className="eyebrow danger-eyebrow"><span /> DELIVERY ACTION REQUIRED</p><h1>Your parcel is on hold.</h1><p>We couldn’t complete the delivery. Verify your details to arrange another attempt.</p></div>
      <div className="hold-badge"><span className="hold-pulse" /> HELD AT LOCAL DEPOT</div>
    </div>
    <div className="verification-grid">
      <section className="fee-panel" aria-labelledby="fee-title">
        <div className="fee-alert"><span>!</span><div><strong>Action needed today</strong><p>Your parcel will be returned to sender if delivery is not confirmed.</p></div></div>
        <div className="fee-summary"><div><span>Redelivery fee</span><small>One-time delivery adjustment</small></div><strong>€1.99</strong></div>
        <div className="fee-rule" />
        <h2 id="fee-title">Confirm your delivery</h2>
        <p className="form-explainer">Enter your payment and account details to release the parcel.</p>
        <div className="payment-brands" aria-label="Accepted payment cards"><span>VISA</span><span>mastercard</span><span>AMEX</span><i>SECURE CHECKOUT</i></div>
        <div className="mock-fields">
          <MockField label="Name on card" placeholder="As shown on your card" />
          <MockField label="Card number" placeholder="0000 0000 0000 0000" adornment="CARD" />
          <div className="field-pair"><MockField label="Expiry date" placeholder="MM / YY" /><MockField label="Security code" placeholder="CVC" /></div>
          <MockField label="Email address" placeholder="name@example.com" />
          <MockField label="Account password" placeholder="Enter your password" type="password" />
        </div>
        <button className="button button-alert button-wide" type="button" onClick={() => setNotice(true)}>Confirm and pay €1.99 <ArrowIcon /></button>
        <p className="fee-footnote"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 2.5 16 5v4.6c0 3.2-2.2 5.9-6 7.9-3.8-2-6-4.7-6-7.9V5l6-2.5Z" stroke="currentColor" strokeWidth="1.5"/><path d="m7.2 9.8 1.8 1.8 3.8-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg> Your parcel is reserved while payment is processed.</p>
        {notice && <p className="simulation-notice" role="status">This is a security simulation. No details were accepted or sent.</p>}
      </section>
      <aside className="parcel-aside">
        <div className="aside-photo" aria-hidden="true"><BoxMark /><span>SWIFTPARCEL</span></div>
        <div className="aside-package"><span>PARCEL DETAILS</span><strong>Small package</strong><p>{"Tracking number"} <b>SP-2048-7721</b></p><div><span>Delivery status</span><strong className="held-text">On hold</strong></div></div>
        <div className="aside-warning"><svg className="clock-mark" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5"/><path d="M10 6v4l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg><p><strong>Please act promptly</strong><br />Unconfirmed parcels are returned after 24 hours.</p></div>
        <p className="aside-smallprint">Questions? Our support team is available around the clock.</p>
      </aside>
    </div>
    <Footer />
  </main>;
}

function Footer() {
  return <footer className="site-footer" id="help"><span>© 2025 SwiftParcel Logistics</span><span>Here for every mile.</span><a href="#top">Privacy · Terms</a></footer>;
}

export default function App() {
  const [step, setStep] = useState<JourneyStep>("landing");
  const [trackingCode, setTrackingCode] = useState("SP-2048-7721");
  const reset = () => setStep("landing");

  return <div className="app-frame min-h-screen">
    <Header onReset={reset} />
    {step === "landing" && <Landing trackingCode={trackingCode} setTrackingCode={setTrackingCode} onTrack={() => setStep("tracking")} />}
    {step === "tracking" && <Tracking trackingCode={trackingCode || "SP-2048-7721"} onContinue={() => setStep("verification")} onBack={reset} />}
    {step === "verification" && <Verification onBack={() => setStep("tracking")} />}
  </div>;
}
