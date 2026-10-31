# Usage controls and simpler My plans

My plans now lists only current saved plan versions. The previous-versions checkbox is removed; saved versions, original conversations, version selection inside an opened plan and direct links remain unchanged.

The usage badge and Coach launcher share one fixed container. Opening, closing or switching assistants moves both controls together without relying on stale screen-coordinate measurements. The badge remains above the Coach label and outside the assistant panel.

The warning button reads Save daily spend warning · no AI. The confirmation reads Daily spend warning saved. Requests remain available at every spend level. Warning calculations, API payloads, schemas, permissions and timezone behavior are unchanged.

Validation: both frontend suites and production builds; focused backend plan, version and cost-history tests; fictional desktop browser checks at 1600 and 1280 pixels. Browser scenarios cover an empty library, two saved versions with one current listing, historical direct-link reload, grouped control geometry for both assistants, scrolling, keyboard activation, and warning save failure/retry/reopen. Provider calls are simulated. No paid user-account request or mobile check is used. Installed localhost is not updated.
