# Personal Details and application filling

Profile → Personal Details saves application names and address information without AI. Legal first name, middle name and family name are explicit fields; preferred first name can follow legal first name or be entered separately. Name on resume is independent. Suggestions from the old resume name remain unsaved until reviewed and saved.

The existing city, state/region and country fields are reused. Street address and ZIP/postal code are application-only. Postal codes remain text, including leading zeros, letters and spaces. Residence does not establish citizenship or work authorization.

GET and PUT `/api/private-application-profile/personal-details` require the signed-in account; PUT also requires CSRF and the revision returned by GET. A stale revision returns 409. A single transaction saves the allowed public contact fields and an encrypted `personal_details` section in the existing private-profile table. Private application fields never enter the general settings response, ordinary account backup, evidence retrieval or resume snapshot. Recover them with the protected installation backup and matching vault key. Personal-details cleanup and private-answer cleanup both remove this encrypted section; account deletion also removes it.

The extension reuses these explicitly saved values for recognized labels and autocomplete attributes when the user starts/resumes filling. Genuine existing values are preserved; missing details, unmatched dropdown choices and failed readback remain in the review checklist. Country/state options use exact normalized matches, and the existing browser rescan handles dependent controls. Authorization, sponsorship and other private disclosures retain their existing review rules.

This update changes the server mappings and Personal Details form. The compatible browser package remains version 1.0.9; no extension permissions or installed Safari/localhost changes are needed.
