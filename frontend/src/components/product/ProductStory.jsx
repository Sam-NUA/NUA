import React from 'react';
import { ArrowUpRight, CalendarDays, Gift, Heart, Check, Sparkles } from 'lucide-react';
import Logo from '../brand/Logo';
import './ProductStory.css';

const products = {
  booking: {
    name: 'Booking', eyebrow: 'FOR CAFÉS, RESTAURANTS & THE PEOPLE WHO RUN THEM',
    headline: 'Make room for more good nights.',
    intro: 'Give guests a simple way to book. Give your team one place to see what’s coming. Keep the POS you already know.',
    icon: CalendarDays, offer: 'Your next chapter starts with a table.',
    features: [['A link worth sharing', 'Send guests straight to your venue’s booking page.'], ['Your day, in view', 'See reservations together and manage changes as plans evolve.'], ['Built around your venue', 'Set opening hours, party sizes and capacity for your service.']],
    faqs: [['Do I need to change my POS?', 'No. Standalone NUA Booking runs alongside your existing POS. Automatic POS sync is not included.'], ['What is included in the pilot?', '14 days of reservation management and a guest booking page, with no card required. Deposits, paid plans, email and SMS reminders are not enabled yet.'], ['What happens after 14 days?', 'New booking activity pauses. Your existing records remain available to view and export; this pilot does not automatically charge you.']],
  },
  loyalty: {
    name: 'Loyalty', eyebrow: 'FOR LOCAL BUSINESSES WITH SOMETHING WORTH RETURNING TO',
    headline: 'Turn “that was lovely” into “see you next week”.',
    intro: 'Build a rewards program that feels like your business. Recognise your regulars, choose your rewards and give customers a reason to come back.',
    icon: Heart, offer: 'Make your regulars feel like regulars.',
    features: [['Your rewards. Your rules.', 'Choose rewards, point costs and lifetime-points tiers.'], ['A place for your members', 'Share a venue link or QR code so members can see points and claim rewards.'], ['Every point accounted for', 'Record manual points adjustments and manage reward claims with a clear history.']],
    faqs: [['Can I keep my existing POS?', 'Yes. This pilot works independently of your POS. Points are awarded manually; automatic Square or other POS sync is not included.'], ['What does the pilot cost?', 'The 14-day pilot has no charge and needs no card. Paid plans are not active, and you will not be automatically billed.'], ['Who supplies the rewards?', 'Your business defines and fulfils its own rewards. NUA tracks points and claims; points are not cash and no joining bonus is promised.']],
  },
};
const routes = [['Booking', 'booking'], ['Loyalty', 'loyalty'], ['Members', 'members']];
function productUrl(product) {
  if (['booking.nuapos.com.au', 'loyalty.nuapos.com.au', 'members.nuapos.com.au', 'app.nuapos.com.au'].includes(window.location.hostname)) return `https://${product}.nuapos.com.au/`;
  return product === 'members' ? '/members' : `/${product}-app`;
}
export function ProductHeader({ name }) {
  return <header className="product-header"><a className="product-identity" href={productUrl(name.toLowerCase())} aria-label={`NUA ${name} home`}><Logo variant="marketing" background="light" size={34} /><span className="product-name">{name}</span></a><nav aria-label="NUA products">{routes.filter(([label]) => label !== name).map(([label, key]) => <a key={key} href={productUrl(key)}>{label}<ArrowUpRight size={13} aria-hidden="true" /></a>)}</nav></header>;
}
export function ProductFooter() {
  return <footer className="product-footer"><Logo background="light" size={24} /><p>More time for people. More reasons to return.</p><a href="mailto:info@nuapos.com.au">Talk to NUA</a></footer>;
}
export function ProductStory({ product, enabled, onStart }) {
  const p = products[product], Symbol = p.icon;
  const request = `mailto:info@nuapos.com.au?subject=${encodeURIComponent(`NUA ${p.name} pilot request`)}&body=${encodeURIComponent('Hello NUA,\n\nI’m interested in the 14-day pilot.\nBusiness name:\nMy name:\nWhat I’d like help with:\n')}`;
  return <section className="product-story" aria-label={`Discover NUA ${p.name}`}><div className="product-story-copy"><p className="product-eyebrow">{p.eyebrow}</p><h1>{p.headline}</h1><p className="product-intro">{p.intro}</p><div className="product-cta-row">{enabled ? <a className="product-cta" href="#product-access" onClick={onStart}>Start my 14-day pilot <ArrowUpRight size={18} aria-hidden="true" /></a> : <a className="product-cta" href={request}>Request pilot access <ArrowUpRight size={18} aria-hidden="true" /></a>}<a href="#product-access">Already with NUA? Sign in</a></div><p className="product-fine">{enabled ? '14 days to explore. No card required. No automatic charge.' : 'Pilot access by request. Opens your email app; access is not guaranteed.'}</p></div><aside className="product-offer"><Symbol size={36} strokeWidth={1.4} aria-hidden="true" /><p className="product-eyebrow">THE NUA PILOT</p><strong>14 days.<br />A fresh possibility.</strong><p>{p.offer}</p><ul>{['No card required', 'Keep your existing POS', 'Your records remain exportable'].map(t => <li key={t}><Check size={16} aria-hidden="true" />{t}</li>)}</ul><span className="product-offer-note">{enabled ? 'Registration is open' : 'Request access to get started'}</span></aside></section>;
}
export function ProductBenefits({ product }) {
  const p = products[product];
  return <><section className="product-benefits" aria-label={`${p.name} benefits`}>{p.features.map(([title, body], i) => <article key={title}><span className="product-number">0{i + 1}</span><h2>{title}</h2><p>{body}</p></article>)}</section><section className="product-faq"><p className="product-eyebrow">A FEW THINGS WORTH KNOWING</p><h2>Good questions. Clear answers.</h2>{p.faqs.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}</section></>;
}
export function MemberBenefits() {
  return <section className="product-benefits member-benefits" aria-label="Membership benefits">{[[Heart, 'Stay close to your favourites', 'Join the loyalty program at your participating venue.'], [Sparkles, 'See your progress', 'Check the points your venue has awarded and your current tier.'], [Gift, 'Choose a little something', 'Claim available rewards when you have enough points. Your venue sets the terms.']].map(([Symbol, title, body]) => <article key={title}><Symbol size={24} strokeWidth={1.5} aria-hidden="true" /><h2>{title}</h2><p>{body}</p></article>)}</section>;
}
