async (page) => {
  "use strict";
  const config = null; // __QA_CONFIG__
  page.setDefaultTimeout(5000);
  page.setDefaultNavigationTimeout(5000);
  const checks = [];
  const errors = [];
  const expected = config.expected_report;
  const rows = expected.decisions || [];
  const check = (name, passed, observed = null) => checks.push({name, passed: Boolean(passed), ...(observed === null ? {} : {observed})});
  const text = (selector) => page.locator(selector).textContent();
  const visible = (selector) => page.locator(selector).isVisible();
  const selectView = async (name) => { await page.locator(`.nav-item[data-view="${name}"]`).evaluate((element) => element.click()); await page.locator(`#view-${name}`).waitFor({state: "visible"}); };
  const filter = async (name) => page.locator(`.filter-tab[data-filter="${name}"]`).evaluate((element) => element.click());
  const search = async (query) => page.locator("#transaction-search").evaluate((element, value) => {element.value=value;element.dispatchEvent(new Event("input",{bubbles:true}));}, query);
  const openTransaction = async (row) => {
    await selectView("review");
    await filter("all");
    await search(row.transaction_id);
    await page.getByRole("button", {name: `Inspect transaction ${row.transaction_id}, ${row.status}`, exact: true}).evaluate((element) => element.click());
  };
  const onError = (error) => errors.push(String(error));
  const contrast = async (label) => {
    const measured = await page.evaluate(() => {
      const rgb = (value) => (value.match(/[\d.]+/g) || []).map(Number);
      const luminance = (value) => value.slice(0, 3).map((channel) => channel / 255).map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      const failures = [];
      let examined = 0;
      let minimum = Infinity;
      for (const element of document.querySelectorAll("body *")) {
        if (!Array.from(element.childNodes).some((child) => child.nodeType === 3 && child.textContent.trim()) || !element.checkVisibility({checkVisibilityCSS: true}) || element.disabled || element.closest("script,style,svg")) continue;
        const style = getComputedStyle(element);
        let parent = element;
        let background = "rgb(255,255,255)";
        while (parent) {
          const value = getComputedStyle(parent).backgroundColor;
          const channels = rgb(value);
          if (channels.length === 3 || (channels.length === 4 && channels[3] === 1)) { background = value; break; }
          parent = parent.parentElement;
        }
        const foregroundLuminance = luminance(rgb(style.color));
        const backgroundLuminance = luminance(rgb(background));
        const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
        const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
        const threshold = large ? 3 : 4.5;
        examined += 1;
        minimum = Math.min(minimum, ratio);
        if (ratio < threshold) failures.push({tag: element.tagName, class: element.className, text: element.textContent.trim().slice(0, 70), color: style.color, background, fontSize: style.fontSize, ratio: Number(ratio.toFixed(3)), threshold});
      }
      return {examined, minimum: Number(minimum.toFixed(3)), failures, scope: "Rendered enabled text nodes against nearest opaque ancestor; 4.5:1 normal text and 3:1 large text. Not a full WCAG conformance audit."};
    });
    check(`${label} text contrast`, measured.examined > 0 && measured.failures.length === 0, measured);
  };
  page.on("pageerror", onError);
  let screenshot = null;
  let actualViewport = null;
  try {
    await page.goto("about:blank");
    await page.setViewportSize({width: config.width, height: config.height});
    await page.setContent(config.html, {waitUntil: "load", timeout: 30000});
    actualViewport = await page.evaluate(() => ({width: innerWidth, height: innerHeight}));
    check("actual browser viewport", actualViewport.width === config.width, actualViewport);

    if (config.scenario === "no_runs") {
      await page.getByRole("heading", {name: "Your first replay starts locally"}).waitFor();
      check("no saved runs state", await visible("#global-message") && !(await visible("#report-content")));
      check("no fabricated run selector", await page.locator("#run-select").isDisabled() && (await text("#run-select")).includes("No saved runs"));
      check("empty-state setup instruction", (await text("#global-message")).includes("make demo"));
      check("exports hidden without run", !(await visible("#export-menu")));
      check("retry keyboard focus", await page.getByRole("button", {name: "Try again"}).isEnabled());
      await page.getByRole("button", {name: "Try again"}).focus();
      await page.keyboard.press("Enter");
      await page.getByRole("heading", {name: "Your first replay starts locally"}).waitFor();
      check("empty retry requests actual captured listing", await page.evaluate(() => window.__qaRequests.length) >= 2);
    } else if (config.scenario === "report_error") {
      await page.getByRole("heading", {name: "This run could not be opened"}).waitFor();
      check("corrupt persisted report error", (await text("#global-message")).includes("cannot be read"));
      check("failed run content hidden", !(await visible("#report-content")) && !(await visible("#export-menu")));
      check("report retry present", await page.getByRole("button", {name: "Try again"}).isVisible());
    } else if (config.scenario === "transport_retry" || config.scenario === "transport_timeout") {
      if (config.scenario === "transport_timeout") check("loading state before timeout", await visible("#global-message") && !(await visible("#report-content")));
      await page.getByRole("heading", {name: "Unable to read local runs"}).waitFor();
      if (config.scenario === "transport_timeout") {
        check("request deadline actually aborts the request", await page.evaluate(() => window.__qaAbortObserved === true));
        check("timeout message is actionable", (await text("#global-message")).includes("request timed out"));
      } else check("transport outage actionable message", (await text("#global-message")).includes("local report server is unavailable"));
      await page.getByRole("button", {name: "Try again"}).evaluate((element) => element.click());
      await page.locator("#report-content").waitFor({state: "visible"});
      check("retry recovers report", (await text("#decision-count")).replaceAll(",", "") === String(rows.length));
      check("error state cleared after recovery", !(await visible("#global-message")));
    } else {
      await page.locator("#report-content").waitFor({state: "visible", timeout: 15000});
      if (config.scenario === "empty_records") {
        check("empty decision table is explicit", await visible("#table-empty") && (await page.locator("#decision-rows tr").count()) === 0);
        check("no invented incident", await visible("#incident-empty") && !(await visible("#incident-content")));
        await selectView("comparison");
        check("empty policy comparison", (await text("#comparison-content")).includes("No policies to compare"));
        await selectView("models");
        check("missing evaluation evidence", (await text("#model-content")).includes("Model evidence is unavailable"));
        await selectView("integrity");
        check("missing integrity is not a pass", (await text("#integrity-content")).includes("Their absence is not a passing result"));
      } else if (config.scenario === "baseline_evidence") {
        await selectView("integrity");
        const baselineCells = await page.locator("#integrity-content tbody tr").evaluateAll((elements) => elements.map((row) => Array.from(row.cells, (cell) => cell.textContent)));
        check("absent feature evidence remains unavailable", baselineCells[0]?.[2] === "0 / 0 · Unavailable");
        check("mixed evidence uses captured-feature denominator", baselineCells[1]?.[2] === "1 / 1 · 100.0%");
        check("legacy baseline keeps its recorded denominator", baselineCells[2]?.[2] === "2 / 2 · 100.0%");
        check("action denominator includes missing feature snapshots", baselineCells.every((cells) => cells[1] === "2 / 2 · 100.0%"));
      } else if (config.scenario === "evidence_counts") {
        const context = await text("#run-context-text");
        check("run distinguishes declined outcomes", context.includes("1 declined outcomes"));
        check("run preserves other unobserved outcomes", context.includes("3 other unobserved"));
        check("run preserves missing feature coverage", context.includes("2 missing historical state"));
        await selectView("models");
        const cards = await page.locator(".maturity-card").evaluateAll((elements) => Object.fromEntries(elements.map((element) => [element.querySelector(".field-label").textContent, element.querySelector("strong").textContent])));
        for (const [label, value] of [["Mature observed", "2"], ["Immature labels", "1"], ["Declined outcomes", "1"], ["Other unobserved", "3"], ["Held-out transactions", "7"], ["Missing historical state", "2"]]) check(`separate evidence card: ${label}`, cards[label] === value, cards[label]);
        check("model shows actual scored mature denominator", (await text("#model-content")).includes("1 / 2 mature labels scored"));
        const cohort = page.locator("#model-content section").filter({has: page.getByRole("heading", {name: "Gradient-boosted model · cohort evidence", exact: true})});
        check("cohort shows scored mature support", (await cohort.textContent()).includes("1 scored mature labels"));
        check("cohort shows missing state support", (await cohort.textContent()).includes("2 missing state"));
      } else if (config.scenario === "untrusted_text") {
        const row = rows.find((item) => item.transaction_id === config.injection_transaction);
        await openTransaction(row);
        await page.locator("#tab-trace").evaluate((element) => element.click());
        check("untrusted text remains literal", (await text("#incident-trace")).includes(config.injection_text));
        check("imported HTML never creates elements", (await page.locator("#incident-trace img, #incident-trace script").count()) === 0);
        check("imported handler never executes", await page.evaluate(() => window.__qaInjected !== true));
      } else if (config.scenario === "partial_runs") {
        check("partial unavailable notice", await visible("#partial-message") && (await text("#partial-message")).includes("ui-broken-report"));
        check("only valid runs selectable", (await page.locator("#run-select option").count()) === 2);
        check("original run selected", (await page.locator("#run-select").inputValue()) === expected.run_id);
        await page.locator("#run-select").evaluate((element) => {element.value="ui-second-saved-run";element.dispatchEvent(new Event("change",{bubbles:true}));});
        await page.waitForFunction(() => document.querySelector("#report-identity").textContent.includes("ui-second-saved-run"), null, {polling:50,timeout:5000});
        check("run selection loads distinct persisted identity", (await text("#report-identity")).includes("ui-second-saved-run"));
        check("served export href follows selected run", (await page.locator("#export-json").getAttribute("href")) === "/api/runs/ui-second-saved-run/export?format=json");
        await page.locator("#run-select").evaluate((element,id) => {element.value=id;element.dispatchEvent(new Event("change",{bubbles:true}));},expected.run_id);
        await page.waitForFunction((id) => document.querySelector("#report-identity").textContent.includes(id), expected.run_id, {polling:50,timeout:5000});
        check("switching back restores original identity", (await text("#report-identity")).includes(expected.run_id));
        const calls = await page.evaluate(() => window.__qaRequests);
        check("UI fetched captured real ASGI route paths", calls.includes("/api/runs") && calls.includes(`/api/runs/${expected.run_id}`) && calls.includes("/api/runs/ui-second-saved-run"), calls);
      } else {
        check("saved report mode is explicit", (await text("#mode-label")) === "SAVED LOCAL RUN");
        check("owned synthetic evidence notice", (await text("#dataset-kind")).includes("SYNTHETIC"));
        check("decision count matches report", (await text("#decision-count")).replaceAll(",", "") === String(rows.length));
        const metricValues = await page.locator(".metric-value").allTextContents();
        check("summary counts match persisted report", ["matched", "mismatched", "incomplete", "changed"].every((key, index) => Number.parseInt(metricValues[index].replaceAll(",", ""), 10) === expected.summary[key]), metricValues);

        for (const status of ["matched", "mismatched", "incomplete"]) {
          await filter(status);
          const matches = rows.filter((row) => row.status === status);
          check(`${status} filter returns correct page size`, (await page.locator("#decision-rows tr").count()) === Math.min(matches.length, 12));
          const textValues = await page.locator("#decision-rows .status-pill").allTextContents();
          check(`${status} filter excludes other statuses`, textValues.every((value) => value === status));
          if (status === "incomplete" && matches.length) check("missing artifacts are visible", (await text("#incident-trace")).includes(matches[0].missing[0]));
        }
        const sunday = rows.find((row) => row.transaction_id === "t-sunday") || rows.find((row) => Object.keys(row.provenance || {}).length);
        if (sunday) {
          await openTransaction(sunday);
          check("transaction search selects exact incident", (await text("#incident-id")) === sunday.transaction_id);
          check("exact cutoff sequence is visible", (await text("#incident-trace")).includes(`decision_time, ${sunday.cutoff_seq}`));
          await page.locator("#tab-features").evaluate((element) => element.click());
          const provenanceIds = Object.values(sunday.provenance || {}).flat();
          check("feature provenance preserves source IDs", provenanceIds.length > 0 && (await text("#incident-features")).includes(provenanceIds[0]));
          const featureText = await text("#incident-features");
          check("historical feature values rendered", Object.entries(sunday.features || {}).every(([key, value]) => featureText.includes(key) && featureText.includes(String(value))));
          await page.locator("#tab-timeline").evaluate((element) => element.click());
          check("timeline count matches persisted evidence", (await page.locator("#incident-timeline .timeline-item").count()) === sunday.timeline.length);
          const excluded = sunday.timeline.filter((event) => !event.included).length;
          check("excluded future evidence remains inspectable", (await page.locator("#incident-timeline .excluded").count()) === excluded);
          const payload = page.locator("#incident-timeline .payload-details").first();
          if (await payload.count()) { await payload.locator("summary").evaluate((element) => element.click()); check("payload expands with evidence", await payload.locator("pre").isVisible()); }
        }

        await page.locator("#tab-trace").focus();
        await page.keyboard.press("ArrowRight");
        check("real keyboard moves to feature tab", await page.locator("#tab-features").evaluate((element) => document.activeElement === element && element.getAttribute("aria-selected") === "true"));
        await page.keyboard.press("End");
        check("keyboard End selects timeline", await page.locator("#tab-timeline").evaluate((element) => document.activeElement === element && element.getAttribute("aria-selected") === "true"));
        await page.keyboard.press("Home");
        check("keyboard Home selects trace", await page.locator("#tab-trace").evaluate((element) => document.activeElement === element && element.getAttribute("aria-selected") === "true"));
        check("one active accessible detail tab", (await page.locator('.detail-tab[aria-selected="true"]').count()) === 1 && (await page.locator('.detail-tab[tabindex="0"]').count()) === 1);
        await page.keyboard.press("/");
        check("slash shortcut focuses search", await page.locator("#transaction-search").evaluate((element) => document.activeElement === element));
        await search("no-such-riskreplay-transaction");
        check("unmatched search shows empty state", await visible("#table-empty") && !(await visible("#incident-content")));
        await page.locator("#clear-filters").evaluate((element) => element.click());
        check("clear search restores records", (await page.locator("#transaction-search").inputValue()) === "" && (await page.locator("#decision-rows tr").count()) > 0);
        const firstPage = await text("#pagination-label");
        if (rows.length > 12) {
          await page.locator("#page-next").evaluate((element) => element.click());
          check("next page advances records", (await text("#pagination-label")) !== firstPage);
          await page.locator("#page-prev").evaluate((element) => element.click());
          check("previous page restores first page", (await text("#pagination-label")) === firstPage);
        }
        const declined = rows.find((row) => row.recorded_action === "decline");
        if (declined) { await openTransaction(declined); check("declined approval outcome explicitly unknown", (await text("#incident-trace")).includes("Outcome under approval is unknown")); }
        await contrast("Decision review");

        await selectView("comparison");
        check("comparison change count matches report", (await text("#comparison-content")).includes(`Changed actions · ${expected.summary.changed.toLocaleString("en-US")}`));
        const originalIds = new Set(rows.map((row) => row.versions?.original_policy).filter(Boolean));
        const identityDetail = page.locator(".policy-card .payload-details").first();
        await identityDetail.locator("summary").evaluate((element) => element.click());
        const identityText = await identityDetail.textContent();
        check("every original policy identity inspectable", Array.from(originalIds).every((id) => identityText.includes(id)));
        check("missing historical policy dependencies disclosed", !rows.some((row) => row.status === "incomplete") || identityText.includes("Evidence gaps"));
        check("counterfactual boundary accompanies changes", (await text("#comparison-content")).includes("Approval outcome unknown") && (await text("#comparison-content")).includes("does not estimate recovered revenue"));
        await contrast("Policy comparison");
        const changedLink = page.locator("#comparison-content .transaction-link").first();
        if (await changedLink.count()) { const id = await changedLink.textContent(); await changedLink.evaluate((element) => element.click()); check("comparison incident link navigates correctly", await visible("#view-review") && (await text("#incident-id")) === id); }

        await selectView("models");
        const evaluation = expected.evaluation;
        const modelText = await text("#model-content");
        check("held-out label denominators match report", modelText.includes(evaluation.splits.test.mature_observed.toLocaleString("en-US")) && modelText.includes(evaluation.splits.test.total.toLocaleString("en-US")));
        check("actual calibration fitting status shown", Object.values(evaluation.models).every((model) => !model.calibration?.status || modelText.includes(model.calibration.status)));
        check("rule scores explicitly uncalibrated", modelText.includes("Fixed heuristic scores · uncalibrated"));
        const calibrationPanel = page.locator("#model-content section").filter({has: page.getByRole("heading", {name: "Calibration evidence", exact: true})});
        const binDetails = calibrationPanel.locator("details");
        for (let index = 0; index < await binDetails.count(); index += 1) await binDetails.nth(index).locator("summary").evaluate((element) => element.click());
        const allModelEntries = [evaluation.rules_baseline, ...Object.values(evaluation.models)].filter(Boolean);
        const binCount = allModelEntries.reduce((sum, model) => sum + (model.metrics?.reliability_bins?.length || 0), 0);
        check("every reliability bin rendered", (await calibrationPanel.locator("tbody tr").count()) === binCount);
        check("empty reliability bins remain unavailable", !allModelEntries.some((model) => model.metrics?.reliability_bins?.some((bin) => bin.count === 0)) || (await calibrationPanel.textContent()).includes("Unavailable"));
        await contrast("Model evidence");

        await selectView("integrity");
        check("all integrity checks rendered", (await page.locator("#integrity-content .check-row").count()) === expected.integrity.checks.length);
        const integrityText = await text("#integrity-content");
        check("baseline raw evidence preserved", expected.baselines.every((baseline) => integrityText.includes(baseline.information_regime)));
        check("single navigation view active", (await page.locator('.nav-item[aria-current="page"]').count()) === 1);
        await contrast("Integrity evidence");

        await page.locator("#export-menu summary").evaluate((element) => element.click());
        check("export menu opens by control", await page.locator("#export-menu").evaluate((element) => element.open));
        for (const [format, filename] of [["json", "report.json"], ["csv", "decisions.csv"], ["html", "report.html"]]) {
          check(`${format} export points at adjacent real artifact`, (await page.locator(`#export-${format}`).getAttribute("href")) === filename && (await page.locator(`#export-${format}`).getAttribute("download")) !== null);
        }
        await page.keyboard.press("Escape");
        check("Escape closes export menu", !(await page.locator("#export-menu").evaluate((element) => element.open)));
        await page.emulateMedia({reducedMotion: "reduce"});
        check("reduced motion preference respected", await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior === "auto"));
        await page.emulateMedia({reducedMotion: "no-preference"});
        await selectView("review");
        await filter("incomplete");
        await search("");
        await page.locator("#tab-trace").evaluate((element) => element.click());
      }
    }
    check("no horizontal page overflow", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), await page.evaluate(() => ({viewport: innerWidth, content: document.documentElement.scrollWidth})));
    const unnamed = await page.locator("button:visible").evaluateAll((buttons) => buttons.filter((button) => !(button.getAttribute("aria-label") || button.textContent).trim()).length);
    check("all visible buttons have accessible text", unnamed === 0, unnamed);
    check("no browser runtime errors", errors.length === 0, errors);
    if (config.scenario !== "saved") await contrast("State fixture");
    await page.evaluate(() => window.scrollTo(0, 0));
    if (config.capture_screenshot) {
      try { await page.screenshot({path: config.screenshot_path, fullPage: false, timeout: 5000}); screenshot = config.screenshot_path; }
      catch (error) { screenshot = {unavailable: String(error)}; }
    } else screenshot = {unavailable: "Separate bounded screenshot attempts timed out after fonts loaded; no fresh screenshot claimed."};
  } catch (error) {
    check("browser interaction completed", false, String(error));
  } finally { page.off("pageerror", onError); }
  return {case: config.name, run_id: config.canonical_run_id, report_semantic_hash: config.report_semantic_hash, source_hashes: config.source_hashes, scenario: config.scenario, viewport: actualViewport, checks, errors, screenshot, protocol: "Real browser component integration; programmatic DOM clicks/input, trusted Playwright keyboard events; in-memory UI and explicit fixture transport; no live HTTP or file navigation"};
}
