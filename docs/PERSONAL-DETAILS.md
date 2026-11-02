# Personal Details and application filling

Profile → Personal Details saves application names and address information without AI. Legal first name, middle name and family name are explicit fields; preferred first name can follow legal first name or be entered separately. Name on resume is independent. Suggestions from the old resume name remain unsaved until reviewed and saved.

The existing city, state/region and country fields are reused. Street address and ZIP/postal code are application-only. Postal codes remain text, including leading zeros, letters and spaces. Residence does not establish citizenship or work authorization.

GET and PUT `/api/private-application-profile/personal-details` require the signed-in account; PUT also requires CSRF and the revision returned by GET. A stale revision returns 409. A single transaction saves the allowed public contact fields and an encrypted `personal_details` section in the existing private-profile table. Private application fields never enter the general settings response, ordinary account backup, evidence retrieval or resume snapshot. Recover them with the protected installation backup and matching vault key. Personal-details cleanup and private-answer cleanup both remove this encrypted section; account deletion also removes it.

The extension reuses these explicitly saved values for recognized labels and autocomplete attributes when the user starts/resumes filling. Genuine existing values are preserved; missing details, unmatched dropdown choices and failed readback remain in the review checklist. Country/state options use exact normalized matches, and the existing browser rescan handles dependent controls. Authorization, sponsorship and other private disclosures retain their existing review rules.

This update changes the server mappings and Personal Details form. The compatible browser package remains version 1.0.9; no extension permissions or installed Safari/localhost changes are needed.

## Saved work authorization and sponsorship

The assistant reuses explicitly saved Yes/No authorization and sponsorship settings for matching, unqualified employer questions when the user starts or resumes filling. A combined now-or-future sponsorship question requires both saved timeframes; it uses Yes if either is Yes and No only when both are No. It never infers authorization from citizenship or residence. Missing/Unsure settings, qualified wording, other countries, ambiguous options and personal attestations remain for review. Existing employer values are preserved and each browser write still requires readback. These values stay encrypted and excluded from AI and employer-document generation. No extension replacement is required for this server mapping.
