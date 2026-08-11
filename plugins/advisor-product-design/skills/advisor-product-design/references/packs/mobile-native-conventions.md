# Pack: Mobile-native conventions

> Researched: 2026-07-18 · Staleness threshold: 12 months
> Load me when: reviewing mobile app designs or cross-platform (Flutter/React Native) builds from engineers whose instincts were formed on desktop dashboards and web CRUD tools; auditing navigation structure, touch targets, form screens, delete/undo flows, or onboarding; deciding whether an iOS design started in 2025+ must adopt the Liquid Glass shell; arbitrating "platform-native vs brand-consistent" disputes with citations instead of taste.

## Entries

### Default to a bottom tab bar, not a hamburger
- **Claim:** Consumer apps with 3-5 peer top-level sections get a bottom tab bar. Reach for a drawer only past ~5 peer sections, and even then keep visible in-page links to the important content. NN/g measured hidden navigation at roughly half the content discoverability of visible nav, with users 15% slower on mobile.
- **Applies when:** Standard consumer CRUD shape — feed, search, create, profile, settings. Any design that ported a desktop sidebar to mobile as a drawer.
- **Fails when:** Deep content hierarchies (retail catalogs, docs) that 5 tabs cannot represent; the mobile penalty is much smaller than desktop (15% vs 39% slower), so a drawer is defensible when top-level links genuinely exceed 4-5. Data is from 2016 website testing, not native apps — treat magnitudes as directional.
- **Source:** Kara Pernice & Raluca Budiu, "Hamburger Menus and Hidden Navigation Hurt UX Metrics," Nielsen Norman Group — https://www.nngroup.com/articles/hamburger-menus/ — 2016-06-26

### Never hide a primary feature in a drawer or overflow
- **Claim:** If a revenue- or retention-critical feature lives only behind a hamburger or overflow menu, it is not discoverable — hiding nav roughly halved discovery and raised task time and perceived difficulty in NN/g's testing. "Users know the hamburger" does not rescue it: they used it in only 57% of mobile cases even when it was the only nav.
- **Applies when:** Diagnosing low engagement on a feature; any screen where the primary task's entry point is behind a tap-to-reveal.
- **Fails when:** Genuinely secondary items — legal, account settings, help — belong in overflow; the finding is about primary tasks. Study was 179 participants on 6 websites, so app-specific numbers may differ.
- **Source:** Kara Pernice & Raluca Budiu, Nielsen Norman Group — https://www.nngroup.com/articles/hamburger-menus/ — 2016-06-26

### Enforce touch-target minimums as a hard gate
- **Claim:** 44x44pt on iOS, 48x48dp on Android with ~8dp spacing between targets. WCAG 2.5.8's 24px AA criterion is a legal floor, not a design target — flag any tappable element below platform minimums, full stop. Dense data-app UIs ported from desktop dashboards are the usual offenders: icon buttons, list-row chevrons, chart drill-downs, dismiss X's.
- **Applies when:** Every tappable element, every review. Non-negotiable for anything shipped.
- **Fails when:** Minimums are still minimums — situational impairment (walking, one-handed, gloves) and motor impairment need more; Apple's own visionOS spec jumps to 60pt where precision drops. WCAG permits sub-24px visuals only when a 24px zone doesn't intersect neighbors — a loophole, not an endorsement.
- **Source:** "All accessible touch target sizes," LogRocket Blog (compiles Apple HIG 44pt, Material 48dp, WCAG 2.5.5/2.5.8, Fluent 40epx, visionOS 60pt) — https://blog.logrocket.com/ux-design/all-accessible-touch-target-sizes/ — accessed 2026-07

### Put high-frequency actions in the bottom half of the screen
- **Claim:** Hoober's 1,333-observation study found 49% one-handed use, and thumbs drive ~75% of touches — top corners are the most expensive real estate on a phone. Primary CTAs, tab bars, and compose buttons go low; reserve the top for infrequent actions (Edit, Settings, filters).
- **Applies when:** Placing primary actions in consumer apps; auditing a design that transplanted desktop top-nav onto mobile.
- **Fails when:** Half of users are NOT one-handed and Hoober himself observed grips shifting "sometimes every few seconds" — the thumb zone is a probability distribution, not a rule. Top placement is fine, even preferable, for destructive or rare actions you want friction on. iOS 26's floating bottom chrome now bakes much of this into the platform — don't double-fix it.
- **Source:** Steven Hoober, "How Do Users Really Hold Mobile Devices?", UXmatters — https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php — 2013-02-18

### Edge-swipe back must work on every pushed iOS screen
- **Claim:** iOS has four back idioms — top-left back button, left-edge swipe, Done for modals, swipe-down for sheets — and no system back button. A custom nav stack that breaks edge-swipe reads as broken to iOS users even when they can't articulate why. Hand-rolled routing in React Native/Flutter is the usual culprit.
- **Applies when:** Any iOS or cross-platform app with custom navigation, custom transitions, or full-screen views.
- **Fails when:** Full-bleed gesture canvases (maps, drawing, games) where edge-swipe collides with content gestures — a visible back/close affordance substitutes there. Android has a system-level back gesture, so back-behavior parity across platforms is neither possible nor desirable.
- **Source:** Erik D. Kennedy, "iOS vs. Android App UI Design: The Complete Guide," Learn UI Design — https://www.learnui.design/blog/ios-vs-android-app-ui-design-complete-guide.html — 2021-08-11

### Don't ship default Material widgets on iOS
- **Claim:** Flutter's out-of-the-box Material switches, alerts, transitions, and scroll physics read as Android on an iPhone. Use `.adaptive()` constructors (Switch, Slider, Checkbox, AlertDialog, etc.) for anything touched daily — and know Flutter does NOT auto-adapt date pickers, tab bars, or IA, which need explicit Cupertino variants. Date pickers, alert dialogs, and page-transition curves are the highest-signal tells in review.
- **Applies when:** Any Flutter consumer app targeting iOS users. React Native gets much of this free by wrapping native components, so the review bar differs by framework.
- **Fails when:** Heavily branded design systems (games, Instagram-class apps) where users judge against the brand, not the platform — a learnable in-app convention beats half-hearted platform mimicry.
- **Source:** Flutter official docs, "Automatic platform adaptations" — https://docs.flutter.dev/ui/adaptive-responsive/platform-adaptations — accessed 2026-07
- **Contested:** Erik D. Kennedy (Learn UI Design, 2021): "no one can tell you not to use tabs on iOS or modal views on Android" if users navigate confidently — platform fidelity is a default, not a law.

### Prefer undo over confirmation for routine deletes
- **Claim:** For frequent, recoverable list deletes (tasks, records, entries), use swipe-action plus a prominent undo snackbar — Gmail's archive is the reference. Routine confirmation dialogs cause habituation: users stop reading and dismiss everything, including the one dialog that mattered. Reserve confirmations for rare, irreversible, high-stakes destructions.
- **Applies when:** CRUD apps where delete/archive is a repeated daily action.
- **Fails when:** Actions with immediate external side effects (sent message, payment, published record) or hard server-side deletion — undo can't cover those, and accidental swipes are a real error class, so truly irreversible items still warrant confirmation (or type-to-confirm). Material canonicalized the undo snackbar; classic iOS leaned on confirmation alerts — porting either blindly reads as foreign.
- **Source:** Maria Panagiotidi, "How to design better destructive action modals," UX Psychology — https://uxpsychology.substack.com/p/how-to-design-better-destructive — 2021-11-01; Angie Li, "Using Swipe to Trigger Contextual Actions," NN/g — https://www.nngroup.com/articles/contextual-swipe/ — 2017-02-12

### Limit swipe to destructive actions, never the only path
- **Claim:** Swipe has no visual signifier and near-zero discoverability, and users expect only destructive/archival actions behind it. Any feature reachable exclusively via swipe (save, share, edit) is a hidden feature. NN/g's named failures: Spotify (same gesture meant save OR remove depending on state), B&H (too many actions per swipe), YouTube (swipe obscured the item being acted on).
- **Applies when:** Any list UI with swipe actions; checking that everything behind a swipe has a visible alternate path.
- **Fails when:** Mail-style apps where configurable left/right swipe pairs are established power-user convention; the guidance predates OS-level swipe standardization, so leading/trailing swipe semantics are more learned now than in 2017.
- **Source:** Angie Li, "Using Swipe to Trigger Contextual Actions," Nielsen Norman Group — https://www.nngroup.com/articles/contextual-swipe/ — 2017-02-12

### Kill the deck-of-cards onboarding carousel
- **Claim:** NN/g's research found upfront tutorials didn't improve task performance. Cut the 3-5 swipeable intro screens; teach contextually at first feature use and spend the effort on a self-evident interface. Users already chose the app — don't re-market it to them at launch.
- **Applies when:** Any consumer app opening with feature-explanation slides or launch-time feature promos.
- **Fails when:** Genuinely novel interaction paradigms justify an interactive walkthrough (learn-by-doing, not read-then-do); setup that gates core function — language, proficiency level, required account data — legitimately belongs upfront. Content customization at onboarding is fine; visual customization belongs in settings.
- **Source:** Alita Kendrick, "Mobile-App Onboarding: An Analysis of Components and Techniques," Nielsen Norman Group — https://www.nngroup.com/articles/mobile-app-onboarding/ — 2020-06-21
- **Contested:** The subscription-growth industry treats the onboarding carousel as a conversion and paywall-placement surface and defends it on revenue grounds, not usability — name the tension explicitly rather than pretending the usability case settles it.

### Mobile forms: one column, labels on top, right keyboard, no lazy dropdowns
- **Claim:** Single-column layout, labels above fields (they survive keyboard-open and zoom states where side labels vanish), and the correct input type for every field so the right keypad appears. Dropdowns are "the UI of last resort" (Wroblewski) — for short option lists use segmented controls, steppers, radio groups, or platform pickers.
- **Applies when:** Any create/edit screen or sign-up flow; especially web `<select>` patterns ported to mobile.
- **Fails when:** Long enumerations (country lists) where a searchable select beats every alternative; label-above costs vertical space on very long forms — the fix is grouping and progressive steps, not side labels. Date/time inputs should use the platform's native picker, not a custom control.
- **Source:** Nick Babich, "Best Practices For Mobile Form Design," Smashing Magazine — https://www.smashingmagazine.com/2018/08/best-practices-for-mobile-form-design/ — 2018-08-28; Luke Wroblewski, "Dropdowns Should be the UI of Last Resort" — https://www.lukew.com/ff/entry.asp?1950 — 2015-07-17

### Respect each platform's primary-action home
- **Claim:** iOS puts the screen's primary action top-right in the nav bar or as a prominent inline button; Android's canonical home is the FAB bottom-right. A FAB transplanted into an iOS app as shorthand for "mobile-looking" is a tell that the designer learned one platform.
- **Applies when:** Reviewing where Create/Add/Compose lives; cross-platform apps sharing one layout.
- **Fails when:** Kennedy's own caveat — cross-platform brand consistency is a legitimate deliberate choice (Google ships FABs in its iOS apps by design-system policy); iOS 26's floating bottom controls and Material 3 Expressive are both reshaping this, so treat it as a convention in motion, not settled law.
- **Source:** Erik D. Kennedy, "iOS vs. Android App UI Design: The Complete Guide," Learn UI Design — https://www.learnui.design/blog/ios-vs-android-app-ui-design-complete-guide.html — 2021-08-11
- **Contested:** Google's own iOS apps and other brand-first design systems prioritize cross-platform consistency over per-platform idiom — and get away with it.

### Design new iOS work against the iOS 26 Liquid Glass shell
- **Claim:** New or refreshed iOS designs target the Liquid Glass template, not the pre-2025 one: the tab bar is a floating, centered, pill-shaped container inset ~21pt from edges, 2-5 destinations, search as a separate circular island; bars float over scrolling content; Liquid Glass belongs on the navigation layer only — never on content like lists. Body text stays 17pt, tap minimum stays 44pt. A Figma mock on the old full-width opaque tab bar needs rework.
- **Applies when:** Any iOS design started or refreshed 2025+.
- **Fails when:** Real, measured legibility problems — NN/g's assessment ("Liquid Glass Is Cracked") and accessibility reviewers reporting contrast as low as 1.5:1 against the 4.5:1 requirement mean text-over-glass needs explicit contrast checks, not faith in Apple. Apps supporting older iOS need graceful fallback; Material 3 Expressive diverges hard, so cross-platform teams cannot share one navigation shell.
- **Source:** Erik D. Kennedy, "iOS 26 Design Guidelines: Illustrated Patterns," Learn UI Design — https://www.learnui.design/blog/ios-design-guidelines-templates.html — 2026, accessed 2026-07; divergence context: 9to5Google, "iOS 26 vs. Android" — https://9to5google.com/2025/06/09/ios-26-android/ — 2025-06-09
- **Contested:** NN/g, "Liquid Glass Is Cracked, and Usability Suffers in iOS 26" — https://www.nngroup.com/articles/liquid-glass/ — plus widespread user criticism at launch (MacRumors, 2025-09); some practitioners deliberately restore opaque chrome where the glass hurts readability.

### Present create/edit as a sheet with an honest dismiss contract
- **Claim:** Self-contained create/edit subtasks on iOS get a modal sheet with explicit Done/Cancel and swipe-down-to-dismiss — a push implies drill-down and is wrong for them. Intercept the dismiss gesture with a save/discard prompt only when there are unsaved changes; a sheet that silently discards edits and a sheet that can't be swiped away both violate iOS expectations.
- **Applies when:** CRUD create/edit flows on iOS; checking push-vs-sheet presentation choices.
- **Fails when:** Multi-step wizards and flows spawning their own sub-hierarchy outgrow a sheet — use full-screen presentation. Android's equivalent is the bottom sheet or full-screen dialog with different dismissal affordances; the gesture contract doesn't port 1:1.
- **Source:** Erik D. Kennedy, "iOS vs. Android App UI Design: The Complete Guide" (iOS dismiss idioms: Done for modals, swipe-down for sheets), Learn UI Design — https://www.learnui.design/blog/ios-vs-android-app-ui-design-complete-guide.html — 2021-08-11

### Audit what earned a tab-bar slot
- **Claim:** Every tab must be a top-level peer destination users revisit. Never a one-shot action (compose is an action button), a marketing surface, or a settings dump — and the active tab state must be visible at all times. On iOS 26 the stakes rose: the pill tab bar can minimize to just the active tab on scroll (`tabBarMinimizeBehavior`), so junk tabs cost more than ever.
- **Applies when:** Any app with bottom navigation; iOS 26 designs using the compact/minimizing tab bar especially.
- **Fails when:** Some established apps successfully use a center tab as an action trigger (camera/compose) — a deliberate, well-known convention violation that works only with a strong icon and instant-action payoff; two-destination utility apps may not need a tab bar at all.
- **Source:** Erik D. Kennedy, "iOS 26 Design Guidelines," Learn UI Design — https://www.learnui.design/blog/ios-design-guidelines-templates.html — 2026, accessed 2026-07; minimize behavior: Apple Developer Documentation, `tabBarMinimizeBehavior(_:)` — https://developer.apple.com/documentation/swiftui/view/tabbarminimizebehavior(_:) — accessed 2026-07
