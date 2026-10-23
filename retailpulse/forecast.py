"""Recursive multi-day forecasts; validation selection and an untouched test period."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import tempfile
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

METHODS = ("Weekly seasonal baseline", "28-day average", "Exponential smoothing", "Holt-Winters", "Random Forest")


def atomic_json(path, document):
    path = Path(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
        json.dump(document, output, indent=2, allow_nan=False)
        temporary = output.name
    os.replace(temporary, path)


def daily_matrix(store):
    meta = store.metadata()
    if not meta.get("coverage_start"):
        raise ValueError("Load a dataset first.")
    end = store.today()-timedelta(days=1) if meta.get("continuous_recording") else pd.Timestamp(meta["coverage_end"]).date()
    days = pd.date_range(meta["coverage_start"], end, freq="D")
    skus = sorted(item["sku"] for item in store.rows("SELECT sku,introduced_on FROM products WHERE active=1")
                  if not item["introduced_on"] or (end-datetime.fromisoformat(item["introduced_on"]).date()).days>=89)
    sales = pd.DataFrame(store.rows("SELECT * FROM daily_sales WHERE day <= ?", (end.isoformat(),)))
    if sales.empty or not skus:
        raise ValueError("Forecasts need sales history and at least 90 complete days for an active product. Billing and stock still work.")
    sales["day"] = pd.to_datetime(sales.day)
    panel = sales.pivot(index="day", columns="sku", values="units").reindex(index=days, columns=skus).fillna(0.0)
    panel.index.name = "day"
    return panel.astype(float)


def features(history, day, sku_index, sku_count):
    values = np.asarray(history, dtype=float)
    if len(values) < 28:
        raise ValueError("At least 28 previous complete days are required for lag features.")
    dow = day.dayofweek
    month = day.month
    return [values[-1], values[-7], values[-14], values[-28],
            float(values[-7:].mean()), float(values[-28:].mean()), float(values[-7:].std()),
            math.sin(2*math.pi*dow/7), math.cos(2*math.pi*dow/7),
            math.sin(2*math.pi*month/12), math.cos(2*math.pi*month/12)] + [float(i == sku_index) for i in range(sku_count)]


def fit_forest(panel):
    x, y = [], []
    for sku_index, sku in enumerate(panel.columns):
        values = panel[sku].to_numpy()
        for index in range(28, len(panel)):
            x.append(features(values[:index], panel.index[index], sku_index, len(panel.columns)))
            y.append(values[index])
    model = RandomForestRegressor(n_estimators=100, max_depth=12, min_samples_leaf=3, random_state=42, n_jobs=2)
    model.fit(np.asarray(x), np.asarray(y))
    return model


def smooth_forecast(values, horizon, seasonal=False):
    """Fixed-parameter additive Holt-Winters (weekly), or simple smoothing."""
    values=np.asarray(values,dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Finite history is required.")
    if not seasonal:
        level=float(values[0])
        for value in values[1:]:
            level=.3*value+.7*level
        return np.full(horizon,max(0.0,level))
    if len(values)<14:
        raise ValueError("Weekly Holt-Winters needs at least two complete weeks for initialization.")
    level=float(values[:7].mean())
    trend=float((values[7:14].mean()-level)/7)
    seasons=(values[:7]-level).copy()
    for t in range(7,len(values)):
        previous=level;position=t%7
        level=.3*(values[t]-seasons[position])+.7*(level+trend)
        trend=.1*(level-previous)+.9*trend
        seasons[position]=.2*(values[t]-level)+.8*seasons[position]
    predictions=np.asarray([level+h*trend+seasons[(len(values)+h-1)%7] for h in range(1,horizon+1)])
    if not np.isfinite(predictions).all():raise ValueError("Holt-Winters produced invalid predictions.")
    return np.maximum(0.0,predictions)


def recursive_forecast(panel, horizon, method, model=None):
    if method not in METHODS:
        raise ValueError("Unknown forecasting method.")
    if method in ("Exponential smoothing","Holt-Winters"):
        return pd.DataFrame({sku:smooth_forecast(panel[sku],horizon,method=="Holt-Winters") for sku in panel.columns},
            index=pd.date_range(panel.index[-1]+pd.Timedelta(days=1),periods=horizon))
    history = [panel[sku].tolist() for sku in panel.columns]
    fixed_means = [float(np.mean(values[-28:])) for values in history]
    predictions = []
    dates = pd.date_range(panel.index[-1]+pd.Timedelta(days=1), periods=horizon)
    for day in dates:
        if method == "Random Forest":
            if model is None:
                raise ValueError("The Random Forest method needs a fitted model.")
            predicted = np.maximum(0.0, model.predict(np.asarray([
                features(values, day, i, len(history)) for i, values in enumerate(history)]))).tolist()
        elif method == "Weekly seasonal baseline":
            predicted = [values[-7] for values in history]
        else:
            predicted = fixed_means[:]
        predictions.append(predicted)
        # Append predictions, never hidden future actual sales, for every horizon step.
        for values, value in zip(history, predicted):
            values.append(float(value))
    return pd.DataFrame(predictions, index=dates, columns=panel.columns)


def metrics(actual, predicted):
    truth, prediction = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    error = truth-prediction
    total = float(np.abs(truth).sum())
    return {"mae": round(float(np.abs(error).mean()), 4),
            "rmse": round(float(np.sqrt(np.square(error).mean())), 4),
            "wape_percent": round(float(np.abs(error).sum()/total*100), 3) if total else None}


def train_mature(store):
    panel = daily_matrix(store)
    if len(panel) < 90:
        raise ValueError("Training needs at least 90 complete calendar days. Historical import still works without training.")
    # Three 7-day validation windows, then a separate final 14-day test.
    validation_truth = []
    validation_predictions = {method: [] for method in METHODS}
    windows = []
    for offset in (35, 28, 21):
        cutoff = len(panel)-offset
        training, actual = panel.iloc[:cutoff], panel.iloc[cutoff:cutoff+7]
        forest = fit_forest(training)
        windows.append({"train_through": training.index[-1].date().isoformat(),
                        "predict_from": actual.index[0].date().isoformat(), "predict_through": actual.index[-1].date().isoformat()})
        validation_truth.append(actual.to_numpy())
        for method in METHODS:
            validation_predictions[method].append(recursive_forecast(training, 7, method, forest).to_numpy())
    truth = np.concatenate(validation_truth)
    validation = {method: metrics(truth, np.concatenate(values)) for method, values in validation_predictions.items()}
    winner = min(METHODS, key=lambda method: validation[method]["mae"])
    test_training, test = panel.iloc[:-14], panel.iloc[-14:]
    test_forest = fit_forest(test_training)
    test_comparison, test_selected = {}, None
    for method in METHODS:
        predicted = recursive_forecast(test_training, 14, method, test_forest)
        test_comparison[method] = metrics(test.to_numpy(), predicted.to_numpy())
        if method == winner:
            test_selected = predicted
    final_forest = fit_forest(panel) if winner == "Random Forest" else None
    future = recursive_forecast(panel, 14, winner, final_forest)
    evaluation = {"selected_method": winner, "selection_metric": "Lowest validation MAE",
        "validation_comparison": validation, "validation_windows": windows,
        "holdout_comparison": test_comparison,
        "holdout_period": {"from": test.index[0].date().isoformat(), "through": test.index[-1].date().isoformat(), "days": 14},
        "holdout_note": "Test scores are reported after selection; they do not choose the model.",
        "data_source": store.metadata()["source"], "complete_days": len(panel), "products": len(panel.columns)}
    rows = [{"date": day.date().isoformat(), "sku": sku, "predicted_units": round(float(value), 3)}
            for day, series in future.iterrows() for sku, value in series.items()]
    test_rows = [{"date": day.date().isoformat(), "sku": sku, "actual_units": float(test.loc[day, sku]),
                  "predicted_units": round(float(test_selected.loc[day, sku]), 3)} for day in test.index for sku in test.columns]
    artifact = {"trained_at": datetime.now(timezone.utc).isoformat(), "train_through": panel.index[-1].date().isoformat(),
        "method": winner, "data_source": store.metadata()["source"], "rows": rows,
        "evaluation": evaluation, "holdout_rows": test_rows}
    atomic_json(store.directory / "forecast.json", artifact)
    return evaluation


def train(store, compare=False):
    """Early per-product estimates; retain validated comparison for mature products."""
    meta = store.metadata()
    if not meta.get("coverage_start"):
        raise ValueError("Set up the shop and record sales first.")
    end = store.today()-timedelta(days=1) if meta.get("continuous_recording") else pd.Timestamp(meta["coverage_end"]).date()
    products = store.rows("SELECT sku,introduced_on FROM products WHERE active=1")
    sales = store.rows("SELECT day,sku,units FROM daily_sales WHERE day<=?", (end.isoformat(),))
    rows, details, early = [], {}, []
    mature = []
    for product in products:
        sku = product["sku"]
        start = max(pd.Timestamp(meta["coverage_start"]).date(), pd.Timestamp(product["introduced_on"]).date() if product["introduced_on"] else pd.Timestamp(meta["coverage_start"]).date())
        days = (end-start).days+1
        own = {row["day"]:row["units"] for row in sales if row["sku"]==sku and row["day"]>=start.isoformat()}
        if days < 3 or not own:
            continue
        if days >= 90 and compare:
            mature.append(sku)
            continue
        values = [float(own.get(day.date().isoformat(),0)) for day in pd.date_range(start,end)]
        def estimate(history):
            if len(history)<7:
                return float(np.mean(history)), "Recent daily average"
            return float(smooth_forecast(history,1)[0]), "Exponential smoothing"
        value, method = estimate(values)
        future_values = [value]*14
        comparison = None
        if compare and days>=28:
            methods=("Exponential smoothing","Holt-Winters")
            validation={name:metrics(values[-14:-7],smooth_forecast(values[:-14],7,name=="Holt-Winters")) for name in methods}
            method=min(methods,key=lambda name:validation[name]["mae"])
            tests={name:metrics(values[-7:],smooth_forecast(values[:-7],7,name=="Holt-Winters")) for name in methods}
            future_values=smooth_forecast(values,14,method=="Holt-Winters").tolist()
            comparison={"validation_comparison":validation,"holdout_comparison":tests,
                "selection_metric":"Lowest validation MAE","validation_days":7,"holdout_days":7,
                "note":"Same dates for both methods. Last 7 days are excluded from model selection. Random Forest waits for 90 complete days."}
        score = None
        if days >= 14:
            held, _ = estimate(values[:-7])
            score = comparison["holdout_comparison"][method] if comparison else metrics(values[-7:],[held]*7)
        details[sku] = {"method":method,"complete_days":days,"early_estimate":days<90,"fast_estimate":True,
            "note":"Fast estimate; limited-history predictions are tentative. No proven advantage over Random Forest.",
            "holdout_score":score,"holdout_days":7 if score else 0,"comparison":comparison}
        early.append(sku)
        rows.extend({"date":(end+timedelta(days=i)).isoformat(),"sku":sku,"predicted_units":round(value,3)} for i,value in enumerate(future_values,1))
    if mature:
        train_mature(store)
        artifact = json.loads((store.directory/"forecast.json").read_text(encoding="utf-8"))
        rows = artifact["rows"]+rows
        for sku in mature:
            details[sku] = {"method":artifact["method"],"early_estimate":False,"validated_comparison":True,"note":"Selected using chronological validation; separate test scores are in Accuracy."}
    else:
        artifact = {"trained_at":datetime.now(timezone.utc).isoformat(),"train_through":end.isoformat(),
            "method":"Early estimates","data_source":meta.get("source","Recorded sales"),
            "evaluation":None,"holdout_rows":[]}
    if not rows:
        raise ValueError("Forecast needs 3 complete days and at least one saved sale for an active product. Today is excluded.")
    artifact["rows"] = rows
    artifact["product_methods"] = details
    artifact["early_products"] = early
    atomic_json(store.directory/"forecast.json",artifact)
    return artifact["evaluation"] or {"selected_method":"Early estimates","products":len(details),"minimum_days":3}
