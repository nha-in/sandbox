/* Project specific Javascript goes here. */

/*
  Copy-to-clipboard and secret reveal, ported from ohcnetwork/experience.

  One delegated listener each, on document, rather than a listener per control:
  these controls arrive with boosted page swaps, and per-element wiring would
  have to be re-run after every swap.

  Both are enhancements. components/secret_value.html renders the secret visible
  and the toggle hidden, so with this file absent the value is still readable;
  the first thing we do here is invert that, which is the only correct order —
  masking before the toggle works would hide a credential behind a dead button.
*/
(() => {
  "use strict";

  const COPIED_MS = 1200;

  function setRevealed(secret, revealed) {
    secret
      .querySelector("[data-secret-mask]")
      ?.classList.toggle("hidden", revealed);
    secret
      .querySelector("[data-secret-value]")
      ?.classList.toggle("hidden", !revealed);
    const toggle = secret.querySelector("[data-secret-toggle]");
    if (!toggle) return;
    toggle.setAttribute("aria-pressed", String(revealed));
    toggle
      .querySelector("[data-icon-show]")
      ?.classList.toggle("hidden", revealed);
    toggle
      .querySelector("[data-icon-hide]")
      ?.classList.toggle("hidden", !revealed);
  }

  function maskSecrets(root) {
    for (const secret of root.querySelectorAll?.("[data-secret]") ?? []) {
      if (secret.dataset.secretReady) continue;
      secret.dataset.secretReady = "1";
      setRevealed(secret, false);
      secret.querySelector("[data-secret-toggle]")?.classList.remove("hidden");
    }
  }

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest?.("[data-secret-toggle]");
    if (!toggle) return;
    setRevealed(
      toggle.closest("[data-secret]"),
      toggle.getAttribute("aria-pressed") !== "true",
    );
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest?.("[data-copy]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
    } catch {
      // Refused (insecure origin, or permission denied). Say nothing and leave
      // the icon alone: the value is selectable text a few pixels away, so the
      // user has a way through that does not need us.
      return;
    }
    const copy = button.querySelector("[data-icon-copy]");
    const done = button.querySelector("[data-icon-done]");
    copy?.classList.add("hidden");
    done?.classList.remove("hidden");
    setTimeout(() => {
      copy?.classList.remove("hidden");
      done?.classList.add("hidden");
    }, COPIED_MS);
  });

  /*
    Keep a collapsed picker's summary in step with its checkboxes.

    Enhancement only: components/form_field.html renders the same sentence
    server-side, so with this file absent the closed summary is still correct
    for the page as loaded — it just goes stale until the next render. The
    wording is duplicated from careui.py on purpose; the alternative is a round
    trip per tick.
  */
  const SUMMARY_NAMED = 3;

  function summarise(picker) {
    const target = picker.querySelector("[data-picker-summary]");
    if (!target) return;
    const labels = [
      ...picker.querySelectorAll("input[type=checkbox]:checked"),
    ].map((box) => box.closest("label")?.textContent.trim() ?? "");
    if (labels.length === 0) {
      target.textContent = target.dataset.pickerEmpty ?? "";
    } else if (labels.length <= SUMMARY_NAMED) {
      target.textContent = labels.join(", ");
    } else {
      const rest = String(labels.length - SUMMARY_NAMED);
      const more = (target.dataset.pickerMore ?? "").replace("{count}", rest);
      target.textContent = `${labels.slice(0, SUMMARY_NAMED).join(", ")} ${more}`;
    }
  }

  document.addEventListener("change", (event) => {
    const picker = event.target.closest?.("[data-picker]");
    if (picker) summarise(picker);
  });

  /*
    Keep the product step's name box showing the product the dropdown points at.

    Enhancement only. Without it the box keeps the name it was rendered with, so
    the screen can disagree with the selection — which is what the box being
    pinned server-side protects against: a name belonging to a product you moved
    away from is ignored, never applied to the one you moved to.
  */
  document.addEventListener("change", (event) => {
    const select = event.target.closest?.("[data-product-select]");
    if (!select) return;
    const box = document.querySelector("[data-product-name]");
    if (!box) return;
    const option = select.selectedOptions[0];
    box.value = option?.value === select.dataset.productNew
      ? ""
      : (option?.textContent.trim() ?? "");
  });

  maskSecrets(document);
  // Boosted swaps bring new markup with them; htmx fires this for every swap.
  document.addEventListener("htmx:afterSwap", (event) =>
    maskSecrets(event.target),
  );
})();
