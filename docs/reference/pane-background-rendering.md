# Pane background rendering and window following

This is the rendering contract for the native macOS app. The optional persona
helper publishes `/tmp/tproj-pane-bg/current.json`; it owns image generation and
tmux layout discovery. The GUI consumes that manifest and never calls an image
provider while rendering. Conversation-main appearance remains defined by
[role mode](role-mode.md).

## Rendering ownership

The backgrounds are a separate, mouse-transparent AppKit window ordered behind
the first on-screen normal Ghostty window. They are not a continuously animated
Ghostty shader. The underlay retains its existing 250 ms geometry/stacking check
and the directory watcher for atomic manifest publication. A static unchanged
manifest does not rebuild the SwiftUI root at each poll.

Portraits are loaded outside SwiftUI's `body`. `FileResourceCache` retains one
resource per distinct path in the rendered manifest. Geometry, active-pane and
conversation-main changes reuse that resource. Before rendering a manifest, the
cache compares nanosecond modification time, file size and device/file number
with one following `stat`, so replacing an
image at the same path invalidates it even if its length and timestamp match.
Manifest decoding uses the same revision check. Missing and corrupt files are
retried when their metadata changes; an optional bad image cannot block workspace
startup.

Switching Space, temporarily hiding Ghostty, or entering fullscreen hides the
underlay without discarding valid content. Reappearance rechecks the files and
window number before reuse. Missing, invalid or empty manifests and controller
detachment release both the cache and the hosting view's image references. A new
rendered manifest evicts paths it no longer uses. There is no accumulating cache
of every project that has ever been shown.

The underlay's own occlusion state is not a visibility signal: transparent
Ghostty can still show it while AppKit considers it covered. Fullscreen and
window selection retain the existing behavior. Colours, image effects, opacity,
main-side rails, active-pane line and pane geometry are unchanged.

## Adaptive window following

The sidebar's `GhosttyWindowTracker` uses these nominal timer intervals:

| Observation | Interval | Reason |
| --- | --- | --- |
| Snapped, observed motion/resize or left-button interaction in Ghostty/tproj | 16 ms | Smooth follow during interaction; retain the burst for 250 ms after its last observation. |
| Visible and stationary, unsnapped, or follow temporarily suspended | 100 ms | Discover the next movement without continuously scanning all windows at 60 Hz. |
| Ghostty absent, or the sidebar hidden/minimized | 500 ms | Recheck availability with fewer wakeups; a hidden sidebar does not scan the desktop. |

The first observation of a drag can wait for the idle interval. Once observed,
fast following resumes. These are scheduling targets, not real-time deadlines;
timer leeway is 2 ms during fast follow and 10 ms otherwise. Burst expiry uses
monotonic uptime. Every return path updates the policy, including initial
absence, reappearance, detach cooldown and suspended drag handling.

The first idle observation must also preserve snap geometry. Target edge/size
changes count as target motion, so a right-edge resize cannot look like the user
pulled the sidebar away. Native sidebar resizing also retains its snap. A
previously top-aligned sidebar stays aligned during resizing or a target move
farther than the normal alignment threshold in one sample; a deliberately
offset sidebar, or an independent sidebar Y drag, keeps its existing Y behavior.

No Accessibility observer or new permission is required. The separate underlay
still checks stacking even while the sidebar is hidden; sidebar visibility is
not used to hide otherwise useful backgrounds.

## Why retain an underlay

Official upstream behavior was checked on 2026-11-07:

- [Ghostty's native background-image](https://ghostty.org/docs/config/reference#background-image)
  belongs to a terminal surface, while this application needs different art and
  role overlays for tmux panes within one surface. Replacing the underlay would
  require composing and publishing a new whole-terminal image on layout and
  role changes. The native option also currently duplicates textures per terminal.
  It is a possible redesign, not a drop-in performance fix.
- Apple documents [window moved](https://developer.apple.com/documentation/applicationservices/kaxwindowmovednotification)
  and [window resized](https://developer.apple.com/documentation/applicationservices/kaxwindowresizednotification)
  Accessibility notifications at the end of those operations. Observers alone do
  not establish smooth live following and introduce an accessibility-trust
  dependency. Bounded polling preserves the current permission model.
- [Ghostty 1.4.0](https://ghostty.org/docs/install/release-notes/1-4-0), released
  2026-10-27, improves its own idle rendering and hidden-tab GPU resource use.
  Those changes do not remove tproj's separate window discovery or image loading.
  The user's installed Ghostty version and local shader/blur settings were not
  observed in this source audit.

The window lookup still selects the first on-screen normal Ghostty window; it
does not prove which window contains the manifest's tmux session. Binding that
identity is separate work. Keep checking the actual window number and stacking
relation rather than assuming an unchanged rectangle identifies the same window.

## Evidence and acceptance

At baseline `91427b7`, snapping selected a permanent 16 ms interval. The revised
stationary tracker requests 10 polls/second instead of 62.5, a nominal 84%
reduction in that tracker's window-list queries. With the separate underlay's
four polls/second, nominal combined steady-state queries change from 66.5 to 14.
These figures follow from the timer settings; they are not measured CPU, GPU,
battery or frame-time improvements. The baseline already avoided replacing an
unchanged SwiftUI root every 250 ms; repeated image construction happened during
view reevaluation, such as layout changes.

`BackgroundPerformanceTests` covers the previously untested cache lifecycle and
cadence/geometry transitions in four tests. It uses real temporary files, an injected
counting loader, a same-size/same-time atomic replacement, resource release
checks, and deterministic observations without sleeps. It does not simulate the
WindowServer or prove rendered appearance.

| Event | Expected result | Evidence needed |
| --- | --- | --- |
| Repeated layout/role changes with unchanged art | Reuse loaded images; no extra loader calls. | Cache regression plus native visual check. |
| Image missing, repaired or atomically replaced at the same path | Use the new revision on the next applicable check. | File/cache regression; native replacement check. |
| Manifest removed while Ghostty is absent | Release cached art and hosting root. | Source ordering; native lifecycle check. |
| Stationary snap, drag, resize, hide and reappearance | Settle to idle; resume fast follow; restore discovery. | Cadence regression plus native drag/Space/fullscreen check. |
| Another app changes the window stack | Repair adjacency without unnecessarily reordering an already adjacent underlay. | Native stacking check; existing ordering rule retained. |

Source/build/automated-test evidence must be reported separately from installed,
loaded and observed GUI behavior. The focused tests and native CI build do not
replace a macOS profile. For a live check, build/launch only through
`apps/tproj/dev-app.sh`, then compare an idle snapped window, live resize,
switching projects, fullscreen, multiple displays and minimize/restore. Record
the tested commit, pane count, image dimensions, display scale and CPU/GPU
observations before claiming an actual performance improvement.

There are no schema, provider or persistent-state migrations. Reverting the GUI
change restores the previous rendering/polling strategy; existing manifests and
image caches remain compatible. This change does not install or restart a live
GUI by itself.
