# REVELA Diagnostic Analytics: D1. Location Patterns
### Comprehensive Mathematical, Algorithmic, and Operational Guide

This document provides an exhaustive, defense-ready explanation of **Section D1: Location Patterns** under REVELA's **Diagnostic Analytics Tier**. It details the exact algorithms, formulas, parameters, and practical interpretations implemented in `revela_backend/api/analytics/routes.py` and visualized in `AnalyticsPage.jsx`.

---

## Executive Overview of D1: Location Patterns

The objective of **Diagnostic Analytics (D1)** is to answer two operational questions for municipal authorities:
1. **Micro-Scale (Street Level):** *"Where are unregistered and non-compliant commercial entities physically clustering along specific streets or alleys?"* $\rightarrow$ Answered by **Nearby Flagged Businesses (DBSCAN Hotspot Intelligence)**.
2. **Macro-Scale (Municipal Level):** *"Are high-risk barangays geographically concentrated in a specific region of the municipality, or are violations spread out evenly across the town?"* $\rightarrow$ Answered by **Severe Flags by Barangay (Centroid-Distance Screening Proxy)**.

```
                                [Severe Flagged Records]
                                (Red & Black Flag Population)
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   ▼
       [D1.1 Nearby Flagged Businesses]                     [D1.2 Severe Flags by Barangay]
             (Micro / Street Scale)                               (Macro / Town Scale)
                    │                                                   │
          DBSCAN Clustering                                   Centroid-Distance Proxy
        (ε = 20m, MinPts = 3)                               (75th Percentile Benchmark)
                    │                                                   │
                    ▼                                                   ▼
   • Hotspot rings (Primary vs Secondary)              • Bar Chart vs Q3 Threshold Line
   • Noise point filtering (-1)                        • Ratio (d_high / d_all)
   • Route-level inspection targets                    • Concentrated vs Dispersed classification
```

---

## 1. D1.1: Nearby Flagged Businesses (DBSCAN Hotspot Clustering)

### 1.1 Algorithmic Purpose
The street-level hotspot view uses **Density-Based Spatial Clustering of Applications with Noise (DBSCAN)**. Unlike partitioning models like $k$-means—which artificially force data into a predefined number of circular clusters—DBSCAN discovers clusters of arbitrary geometry based strictly on spatial density, while identifying isolated violations as statistical noise.

### 1.2 Target Population
Only **severe non-compliant flags** are evaluated:
* **Red Flags:** Commercial entities detected via Google Places scraping with no corresponding entry in the BPLO registry.
* **Black Flags:** Establishments with revoked permits or blacklisted/non-responsive status.
*(Green, Yellow, and Orange flags are excluded from hotspot clustering so that compliance inspection resources focus exclusively on acute violations).*

---

### 1.3 Mathematical Formulas & Conversion

#### Step 1: Spherical Coordinate Conversion
Geodetic latitude ($\phi$) and longitude ($\lambda$) stored in degrees are converted to radians:
$$\phi_{\text{rad}} = \phi_{\text{deg}} \times \frac{\pi}{180}, \quad \lambda_{\text{rad}} = \lambda_{\text{deg}} \times \frac{\pi}{180}$$

#### Step 2: Haversine Great-Circle Distance
To measure surface distance across the Earth's curvature without planar projection distortion, pairwise distances are calculated using the **Haversine formula**:

$$\Delta \phi = \phi_2 - \phi_1, \quad \Delta \lambda = \lambda_2 - \lambda_1$$

$$a = \sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1) \cdot \cos(\phi_2) \cdot \sin^2\left(\frac{\Delta \lambda}{2}\right)$$

$$c = 2 \cdot \operatorname{atan2}\left(\sqrt{a}, \sqrt{1 - a}\right)$$

$$d = R \cdot c$$

where:
* $d$ is the surface geodesic distance between two points in meters.
* $R = 6,371,008.8\text{ meters}$ (the mean volumetric radius of the Earth).

#### Step 3: Parameter Epsilon ($\varepsilon$) & Conversion to Radians
* **Physical Search Radius ($\varepsilon$):** Exactly **20 meters** (`0.02 km`).
* **Conversion to Radians:** Because scikit-learn's `haversine` metric requires radians:
$$\varepsilon_{\text{rad}} = \frac{\varepsilon_{\text{km}}}{R_{\text{km}}} = \frac{0.02}{6,371.0088} \approx 3.1392 \times 10^{-6}\text{ radians}$$

#### Step 4: Minimum Cluster Size ($MinPts$)
$$MinPts = 3$$

---

### 1.4 How DBSCAN Classifies Points

For each record $p$:
1. **$\varepsilon$-Neighborhood Definition:**
   $$N_\varepsilon(p) = \{ q \in D \mid \text{dist}_{\text{haversine}}(p, q) \le \varepsilon_{\text{rad}} \}$$
2. **Core Point:** If $|N_\varepsilon(p)| \ge MinPts$ (at least 3 records within 20 meters).
3. **Border Point:** If $|N_\varepsilon(p)| < MinPts$, but $p$ belongs to the neighborhood of a core point.
4. **Noise Point ($label = -1$):** If $p$ is neither a core point nor a border point.

#### Centroid Calculation & Cluster Sizing
For every valid cluster $C_k$ ($k \ge 0$):
* **Centroid Coordinates:** The arithmetic mean of member coordinates:
  $$\bar{\phi}_k = \frac{1}{|C_k|} \sum_{i \in C_k} \phi_i, \quad \bar{\lambda}_k = \frac{1}{|C_k|} \sum_{i \in C_k} \lambda_i$$
* **Cluster Display Radius ($r_k$):** The maximum geodesic distance from the centroid to any member, bounded to a minimum of 20 meters:
  $$r_k = \max\left(\max_{i \in C_k} \text{geodesic}(\text{centroid}_k, \text{point}_i), 20\text{ m}\right)$$

---

### 1.5 UI Visual Elements & Interpretation

| Visual Element | Color / Style | Meaning in System |
| :--- | :--- | :--- |
| **Primary Hotspot Ring** | **Large Indigo Ring (`#6366f1`)** | The **largest nearby group** (highest flag count in the municipality). E.g., *"21 flagged records around Barangay Bayorbor"*. |
| **Secondary Hotspot Rings** | **Orange Rings** | Smaller dense clusters satisfying $\varepsilon = 20\text{ m}$, $MinPts \ge 3$. |
| **Cluster Member Dots** | **Indigo / Orange Solid Dots** | Individual establishments participating in an identified cluster. |
| **Noise Dots** | **Muted Slate Grey Dots** | **Isolated flagged records ($label = -1$)** with no neighbors within 20m. E.g., *"Hubensio's Buffalo Wings Store · No nearby group"*. |

#### How to Interpret the Dynamic Narrative:
> *"Largest nearby group: 21 flagged records around Barangay Bayorbor. Consider prioritizing this area for inspection; proximity alone does not confirm a violation."*
* **Operational Meaning:** 21 unregistered/blacklisted entities operate within overlapping 20-meter spans in Bayorbor.
* **Administrative Value:** The BPLO should deploy field inspectors along this specific street stretch to achieve high inspection throughput in a single site visit.
* **Disclaimer:** Physical proximity implies spatial clustering, but each establishment must be audited independently for due process.

---

## 2. D1.2: Severe Flags by Barangay (Centroid-Distance Screening Proxy)

### 2.1 Algorithmic Purpose
While DBSCAN operates at the micro street level, the **Severe Flags by Barangay** component evaluates town-wide spatial distribution across Mataasnakahoy's **16 constituent barangays**. 

Rather than computing a formal inferential Moran's $I$ test statistic (which requires complex spatial weight matrices and normal distribution assumptions), REVELA implements a **Moran-style centroid-distance screening proxy** to determine whether severe non-compliance is regionally clustered or evenly scattered.

---

### 2.2 Mathematical Step-by-Step Procedure

#### Step 1: Barangay-Level Aggregation
For each of the 16 barangays $b \in \{1, 2, \dots, 16\}$, the total count of severe flags ($y_b$) is computed:
$$y_b = \sum \mathbb{I}(\text{flagColor} \in \{\text{'Red'}, \text{'Black'}\})$$

The mean centroid $(\phi_b, \lambda_b)$ of severe records in that barangay is also calculated:
$$\phi_b = \frac{1}{y_b} \sum \phi_i, \quad \lambda_b = \frac{1}{y_b} \sum \lambda_i$$

#### Step 2: Upper-Quartile Benchmark ($Q_3$ / 75th Percentile)
The system sorts all barangay counts $\{y_1, y_2, \dots, y_{16}\}$ in ascending order and computes the 75th percentile:
$$\text{Threshold } T = P_{75}(y)$$

* **High-Risk Units:** Any barangay with $y_b > T$ and $y_b > 0$.
*(In the live system, 4 out of 16 barangays typically fall above the upper quartile).*

#### Step 3: Mean Inter-Centroid Geodesic Distances
1. **Global Municipal Mean Distance ($\bar{d}_{\text{all}}$):**
   Calculates the mean Haversine distance between all pairs of barangay centroids:
   $$\bar{d}_{\text{all}} = \frac{1}{\binom{N}{2}} \sum_{i < j} d(\text{centroid}_i, \text{centroid}_j)$$
   *(For $N=16$, there are $\binom{16}{2} = 120$ unique pairwise inter-barangay distances).*

2. **High-Risk Mean Distance ($\bar{d}_{\text{high}}$):**
   Calculates the mean Haversine distance among only the high-risk barangay centroids ($K$ units):
   $$\bar{d}_{\text{high}} = \frac{1}{\binom{K}{2}} \sum_{i < j, \, i,j \in \text{High-Risk}} d(\text{centroid}_i, \text{centroid}_j)$$

#### Step 4: Spatial Autocorrelation Ratio & Classification
The dispersion ratio is evaluated:
$$\text{Ratio} = \frac{\bar{d}_{\text{high}}}{\bar{d}_{\text{all}}}$$

The system evaluates three discrete classification branches:

```
                          Ratio = d_high / d_all
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
   Ratio < 0.85          0.85 <= Ratio <= 1.15            Ratio > 1.15
         │                          │                          │
[Concentrated Regional]     [Random Dispersion]       [Dispersed Municipal]
High-risk towns are       Neither unusually close     High-risk towns sit on
clustered together.       nor unusually separated.    opposite borders of town.
```

1. **State 1: Concentrated Regional Risk ($\text{Ratio} < 0.85$)**
   * *Criterion:* $\bar{d}_{\text{high}} < 0.85 \times \bar{d}_{\text{all}}$.
   * *Meaning:* High-risk barangays are physically closer to each other than the municipal average.
   * *Directional Vector:* The engine compares the centroid of high-risk barangays $(\bar{\phi}_{\text{hr}}, \bar{\lambda}_{\text{hr}})$ against the municipal centroid $(\bar{\phi}_{\text{all}}, \bar{\lambda}_{\text{all}})$:
     $$\text{NS} = \begin{cases} \text{Northern}, & \text{if } \bar{\phi}_{\text{hr}} > \bar{\phi}_{\text{all}} \\ \text{Southern}, & \text{if } \bar{\phi}_{\text{hr}} \le \bar{\phi}_{\text{all}} \end{cases}, \quad \text{EW} = \begin{cases} \text{Eastern}, & \text{if } \bar{\lambda}_{\text{hr}} > \bar{\lambda}_{\text{all}} \\ \text{Western}, & \text{if } \bar{\lambda}_{\text{hr}} \le \bar{\lambda}_{\text{all}} \end{cases}$$
   * *Dynamic Narrative Output:*
     > *"Several higher-risk barangays are relatively close together, mainly in the [NS]-[EW] area. This is a geographic screening signal, not evidence of a shared cause."*

2. **State 2: Dispersed Municipal Risk ($\text{Ratio} > 1.15$)**
   * *Criterion:* $\bar{d}_{\text{high}} > 1.15 \times \bar{d}_{\text{all}}$.
   * *Meaning:* High-risk barangays are located at opposite ends of the municipality (e.g., one on the lakeshore, one on the highway border), indicating decentralized violations.
   * *Dynamic Narrative Output:*
     > *"Higher-risk barangays are spread farther apart than average, so no single regional group stands out."*

3. **State 3: Random / Neutral Spatial Dispersion ($0.85 \le \text{Ratio} \le 1.15$)**
   * *Criterion:* The ratio sits within $\pm 15\%$ of the municipal baseline.
   * *Meaning:* Non-compliance is neither heavily clustered nor unusually dispersed.
   * *Dynamic Narrative Output (As seen on your live dashboard screen):*
     > *"Higher-risk barangays are neither notably close together nor unusually spread out."*

---

### 2.3 UI Visual Elements & Interpretation

| Visual Element | Appearance | Interpretation |
| :--- | :--- | :--- |
| **Upper-Quartile Benchmark Line** | Horizontal dashed line (`#6366f1`) | Set at the 75th percentile ($Q_3 \approx 48$ flags). Defines the statistical threshold for high-priority barangays. |
| **High-Risk Bars** | **Dark Blue / Indigo Bars (`#6366f1`)** | Barangays exceeding the $Q_3$ line (e.g., **Brgy. Bayorbor**, **Brgy. Santol**, **Brgy. III**, **Brgy. Kinalaglagan**). |
| **Standard-Risk Bars** | **Light Purple Bars (`#8b5cf6`, 40% opacity)** | Barangays below the upper quartile (e.g., Brgy. Loob with 13 flags). |

#### How to Interpret the Macro Screen:
1. **Screening, Not Cause:** The subtitle explicitly warns: *"This is a screening comparison, not a measure of cause."* Having more flags may simply reflect higher commercial density or recent Google Maps indexing, rather than systemic evasion.
2. **Resource Strategy:** 
   * If **Concentrated**: Conduct a multi-barangay regional enforcement blitz in the identified quadrant (e.g., North-Western corridor).
   * If **Neutral / Dispersed**: Distribute inspection personnel proportionally according to each barangay's individual bar height.

---

## 3. Summary Comparison: D1.1 (DBSCAN) vs. D1.2 (Moran's Proxy)

| Feature | D1.1: Nearby Flagged Businesses | D1.2: Severe Flags by Barangay |
| :--- | :--- | :--- |
| **Spatial Scale** | **Micro (Street / Alley level)** | **Macro (Barangay / Municipal level)** |
| **Underlying Technique** | **DBSCAN Clustering** | **Centroid-Distance Dispersion Proxy** |
| **Data Unit** | Individual establishment coordinate pins | Barangay administrative totals (16 units) |
| **Distance Metric** | Haversine Great-Circle ($\varepsilon = 20\text{ m}$) | Inter-Centroid Haversine Distances |
| **Cut-Off Criterion** | Radius $\le 20\text{ m}$ & Count $\ge 3$ | Upper Quartile ($P_{75}$) & Ratio ($0.85\text{–}1.15$) |
| **Noise Handling** | Points with $< 2$ neighbors labeled noise ($label = -1$) | Low-violation barangays rendered in muted purple |
| **Key Output** | Inspection cluster circles & member lists | Regional distribution narrative & risk bars |
| **Primary User Action** | Dispatches inspectors to specific street blocks | Guides municipal-wide enforcement budgeting and policy |
