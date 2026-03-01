# Glossary

Canonical terms used across SD, dMFA, coupling, and scenario configs.

## Model structure

- **Loose iterative coupling**: SD and dMFA are solved repeatedly per run until coupling signals converge.
- **Slice**: a `material x region` model partition.
- **Reporting phase**: years `>= report_start_year`.
- **Historic/calibration phase**: years `< report_start_year`.

## Demand, service, and stress

- **Desired demand**: exogenous demand trajectory consumed by SD.
- **Service demand**: demand passed into dMFA after SD demand response.
- **Delivered service**: fulfilled service from dMFA outputs.
- **Unmet service**: `max(service_demand - delivered_service, 0)`.
- **Service stress signal**: `unmet_service / service_demand`.
- **Circular supply stress signal**: `1 - secondary_supply / (primary_supply + secondary_supply)`.

## Endogenous SD loop terms

- **Capacity envelope**: lagged index representing effective throughput headroom.
- **Flow utilization**: desired-demand pressure relative to envelope-constrained flow capacity.
- **Bottleneck pressure**: `max(flow_utilization - 1, 0)`.
- **Scarcity multiplier effective**: scarcity multiplier after bottleneck amplification.
- **Price ratio**: relative price against baseline (`price / price_base`).

## Collection and circularity

- **Collection multiplier**: SD-controlled multiplier applied to base collection rate.
- **Collection bottleneck throttle**: dampening factor that weakens collection response under bottlenecks.
- **New scrap**: pre-use fabrication losses.
- **Old scrap**: post-use end-of-life outflow.

## Stocks and inventories

- **Refinery stockpile**: operational secondary inventory (`refinery_stockpile_native`).
- **Strategic inventory**: policy reserve stock (`strategic_inventory_native`).
- **Terminal inventory**: positive stock remaining in final modeled year; not auto-flushed as loss.

## Primary supply terms

- **Primary refined output**: domestic primary refined metal output.
- **Primary refined net imports**: net refined imports.
- **Primary available to refining**: `max(0, primary_refined_output + primary_refined_net_imports)`.

## Temporal config forms

- **Scalar parameter**: single value across all modeled years.
- **Year-gated parameter**: value activated from `start_year` forward.
- **Full timeseries parameter**: explicit yearly vector over modeled horizon.
