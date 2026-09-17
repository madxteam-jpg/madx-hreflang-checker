from urllib.parse import urljoin
import asyncio
import io
import sys
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import pandas as pd
from playwright.async_api import async_playwright
import streamlit as st

# Windows workaround for asyncio loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.set_page_config(
    page_title="Hreflang Cluster Auditor", layout="wide", page_icon="🌐"
)

st.title("🌐 Playwright Hreflang Cluster Auditor")
st.markdown(
    "Audit homepage clusters for reciprocity, canonical alignment, self-references, and missing market locales."
)

st.sidebar.header("Audit Configuration")
timeout_sec = st.sidebar.slider("Timeout (seconds)", 5, 60, 20)

urls_input = st.text_area(
    "Enter Homepage URLs (one per line):",
    height=150,
    placeholder="https://www.puprime.com/\nhttps://www.puprime.com/ru/",
)


def generate_png_summary(df):
    """Generates a styled PNG image summary of the audit results using Matplotlib."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
    ax.axis("tight")
    ax.axis("off")

    summary_df = df[
        [
            "Source URL",
            "Status Code",
            "Self Reference",
            "Missing Locales",
            "Non-Reciprocal",
            "Overall Health",
        ]
    ].copy()

    summary_df["Source URL"] = summary_df["Source URL"].apply(
        lambda x: x[:32] + "..." if len(x) > 32 else x
    )

    table_data = [summary_df.columns.values.tolist()] + summary_df.values.tolist()

    table = ax.table(
        cellText=table_data, colLabels=None, cellLoc="center", loc="center"
    )

    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    header_color = "#1E3A8A"
    for i in range(len(summary_df.columns)):
        cell = table[0, i]
        cell.set_facecolor(header_color)
        cell.set_text_props(color="white", weight="bold")

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.2)
    buffer.seek(0)
    plt.close(fig)
    return buffer


async def fetch_page_with_playwright(url, timeout):
    """Uses Playwright Chromium instance to bypass Cloudflare bot challenges."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=timeout * 1000
            )
            status_code = response.status if response else 200
            final_url = page.url
            html_content = await page.content()
            await browser.close()
            return {
                "status_code": status_code,
                "final_url": final_url,
                "html": html_content,
                "error": None,
            }
        except Exception as e:
            await browser.close()
            return {
                "status_code": None,
                "final_url": None,
                "html": "",
                "error": str(e),
            }


def audit_cluster(urls, timeout=20):
    cluster_data = {}
    master_targets = {}

    # Step 1: Crawl with Playwright headless browser
    for url in urls:
        fetch_res = asyncio.run(fetch_page_with_playwright(url, timeout))

        if fetch_res["error"]:
            cluster_data[url] = {
                "status_code": None,
                "final_url": None,
                "is_redirected": False,
                "canonical": None,
                "hreflangs": {},
                "error": fetch_res["error"],
            }
            continue

        soup = BeautifulSoup(fetch_res["html"], "html.parser")

        canonical_tag = soup.find("link", rel="canonical")
        canonical_url = (
            canonical_tag.get("href").strip() if canonical_tag else None
        )

        hreflangs = {}
        for link in soup.find_all("link", rel="alternate"):
            lang = link.get("hreflang")
            href = link.get("href")
            if lang and href:
                clean_lang = lang.lower().strip()
                full_href = urljoin(url, href.strip())
                hreflangs[clean_lang] = full_href

                if clean_lang not in master_targets:
                    master_targets[clean_lang] = full_href

        cluster_data[url] = {
            "status_code": fetch_res["status_code"],
            "final_url": fetch_res["final_url"],
            "is_redirected": fetch_res["final_url"].rstrip("/") != url.rstrip("/"),
            "canonical": canonical_url,
            "hreflangs": hreflangs,
            "error": None,
        }

    # Step 2: Reciprocity & Consistency Checks
    rows = []
    for url in urls:
        d = cluster_data[url]

        if d["error"]:
            rows.append({
                "Source URL": url,
                "Status Code": "ERR",
                "Self Reference": "FAIL",
                "Canonical Match": "N/A",
                "Total Locales": 0,
                "Missing Locales": len(master_targets),
                "Non-Reciprocal": 0,
                "Audit Summary": f"Fetch Error: {d['error']}",
                "Overall Health": "CRITICAL",
            })
            continue

        declared_urls = set(d["hreflangs"].values())
        has_self_ref = url.rstrip("/") in [
            target.rstrip("/") for target in declared_urls
        ]

        canonical_ok = True
        if d["canonical"]:
            canonical_ok = d["canonical"].rstrip("/") == url.rstrip("/")

        missing_locales = [
            lang for lang in master_targets if lang not in d["hreflangs"]
        ]

        non_reciprocal_count = 0
        for lang, target_url in d["hreflangs"].items():
            if (
                target_url in cluster_data
                and cluster_data[target_url]["hreflangs"]
            ):
                target_declared_urls = [
                    u.rstrip("/")
                    for u in cluster_data[target_url]["hreflangs"].values()
                ]
                if url.rstrip("/") not in target_declared_urls:
                    non_reciprocal_count += 1

        issues = []
        if d["status_code"] != 200:
            issues.append(f"HTTP {d['status_code']}")
        if not has_self_ref:
            issues.append("Missing Self-Reference")
        if d["is_redirected"]:
            issues.append(f"Redirects to {d['final_url']}")
        if not canonical_ok:
            issues.append(f"Canonical mismatch ({d['canonical']})")
        if missing_locales:
            issues.append(
                f"Missing {len(missing_locales)} locale(s): {', '.join(missing_locales)}"
            )
        if non_reciprocal_count > 0:
            issues.append(
                f"{non_reciprocal_count} non-reciprocal return link(s)"
            )

        if d["status_code"] != 200 or not canonical_ok or not has_self_ref:
            health = "CRITICAL"
        elif issues:
            health = "WARNING"
        else:
            health = "PASS"

        rows.append({
            "Source URL": url,
            "Status Code": d["status_code"],
            "Self Reference": "PASS" if has_self_ref else "FAIL",
            "Canonical Match": "PASS" if canonical_ok else "FAIL",
            "Total Locales": len(d["hreflangs"]),
            "Missing Locales": len(missing_locales),
            "Non-Reciprocal": non_reciprocal_count,
            "Audit Summary": "; ".join(issues)
            if issues
            else "Fully Reciprocal & Complete",
            "Overall Health": health,
        })

    return pd.DataFrame(rows), cluster_data


# Streamlit UI
if st.button("🚀 Run Playwright Audit", type="primary"):
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]
    if not urls:
        st.warning("Please enter at least one URL.")
    else:
        with st.spinner("Launching Chromium to pass Cloudflare verification..."):
            df_results, cluster_data = audit_cluster(urls, timeout_sec)

        st.subheader("📊 Executive Audit Summary")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total URLs Audited", len(df_results))
        col2.metric(
            "Compliant Cluster URLs",
            len(df_results[df_results["Overall Health"] == "PASS"]),
        )
        col3.metric(
            "Warnings", len(df_results[df_results["Overall Health"] == "WARNING"])
        )
        col4.metric(
            "Critical Errors",
            len(df_results[df_results["Overall Health"] == "CRITICAL"]),
        )

        st.dataframe(df_results, use_container_width=True)

        st.markdown("### 📥 Download Reports")
        col_csv, col_png = st.columns(2)

        csv_data = df_results.to_csv(index=False).encode("utf-8")
        col_csv.download_button(
            label="📄 Download Report (CSV)",
            data=csv_data,
            file_name="hreflang_audit_report.csv",
            mime="text/csv",
        )

        png_buffer = generate_png_summary(df_results)
        col_png.download_button(
            label="🖼️ Download Summary Table (PNG)",
            data=png_buffer.getvalue(),
            file_name="hreflang_audit_summary.png",
            mime="image/png",
        )

        st.markdown("---")
        st.subheader("🔎 Detailed Cluster Diagnostics")
        for url in urls:
            data = cluster_data[url]
            with st.expander(f"Diagnostics: {url}"):
                if data["error"]:
                    st.error(f"Error fetching URL: {data['error']}")
                else:
                    st.write(f"**Final Response URL:** `{data['final_url']}`")
                    st.write(f"**Canonical Target:** `{data['canonical']}`")
                    st.write("**Declared Locales:**")
                    st.json(data["hreflangs"])
