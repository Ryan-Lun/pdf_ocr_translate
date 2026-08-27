# Template payloads are shared while source artifacts remain protected

Status: accepted

Saved document template payloads are reusable team assets, but the source job artifacts used to create them may contain original document content. Sharing a template must not imply that every user can read the template source PDF, debug PDF, or other sensitive source artifacts.

## Considered Options

- Make all template-related data private to the owner. This protects source content but weakens the template reuse workflow.
- Share both template payloads and all template source job artifacts. This is convenient but overexposes original documents and OCR/debug output.
- Share saved template payloads, while keeping sensitive source artifacts owner/admin-only and allowing only explicitly safe preview artifacts to be shared. This preserves reuse without widening access to source documents.

## Consequences

Template payload APIs can remain shared according to the product model. Job artifact access must distinguish reusable template data from sensitive source files. Owners and admins can access template source artifacts; non-owner editors can access only artifacts that are deliberately allowlisted as safe previews.
