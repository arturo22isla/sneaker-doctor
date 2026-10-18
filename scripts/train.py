"""Entrena el clasificador de material con transfer learning (EfficientNetB0).

Etapa 1 (siempre, corre también sin GPU): la red base congelada calcula las
características de cada foto una sola vez y solo se entrena la capa final.
Etapa 2 (opcional, con GPU): fine-tuning. Se descongelan las últimas capas de la red
base y se entrena todo con data augmentation (giros, zoom, contraste) y learning rate bajo.

Uso:
    python scripts/train.py                                   # solo etapa 1
    python scripts/train.py --finetune-epochs 6               # etapa 1 + fine-tuning (Colab con GPU)
    python scripts/train.py --extra data/processed/cleanlab.csv --finetune-epochs 6   # suma fotos de Clean Lab

Salida en models/: sneaker_doctor.keras, labels.json, metrics.json, errores_prueba.csv
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sneaker_doctor import MATERIALS  # noqa: E402
from sneaker_doctor.vision import IMG_SIZE, preprocess  # noqa: E402


def load_images(paths, batch=64):
    """Genera lotes de imágenes preprocesadas igual que en la app."""
    for i in range(0, len(paths), batch):
        yield np.concatenate([preprocess(Image.open(p)) for p in paths[i:i + batch]])


def embed(base, paths, cache: Path):
    if cache.exists():
        return np.load(cache)["x"]
    feats = [base.predict(b, verbose=0) for b in load_images(list(paths))]
    x = np.concatenate(feats) if feats else np.zeros((0, base.output_shape[-1]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, x=x)
    return x


def evaluate(pred, y, df_idx, df, train_y):
    """Acierto general, por fuente (Kaggle / Clean Lab) y matriz de confusión."""
    acc = float((pred == y).mean())
    majority = int(np.bincount(train_y).argmax())
    by_source = {src: float((pred[mask] == y[mask]).mean())
                 for src in df.loc[df_idx, "source"].unique()
                 for mask in [(df.loc[df_idx, "source"] == src).to_numpy()] if mask.any()}
    confusion = pd.crosstab(pd.Series([MATERIALS[i] for i in y], name="real"),
                            pd.Series([MATERIALS[i] for i in pred], name="predicho"))
    per_class = {MATERIALS[c]: float((pred[y == c] == c).mean()) for c in np.unique(y)}
    return {"test_accuracy": acc, "baseline_accuracy": float((y == majority).mean()),
            "accuracy_por_fuente": by_source, "accuracy_por_material": per_class, "confusion": confusion.to_dict()}, confusion


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=str(ROOT / "data" / "processed" / "images.csv"))
    ap.add_argument("--extra", default="", help="CSV adicional con fotos de Clean Lab (mismas columnas)")
    ap.add_argument("--extra-weight", type=int, default=3, help="Veces que se repiten las fotos de Clean Lab en entrenamiento")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--finetune-epochs", type=int, default=0, help="0 = sin fine-tuning")
    ap.add_argument("--finetune-layers", type=int, default=40, help="Capas finales de la red base que se descongelan")
    ap.add_argument("--out", default=str(ROOT / "models"))
    args = ap.parse_args()

    import tensorflow as tf
    from tensorflow.keras import layers

    df = pd.read_csv(args.images)
    if "source" not in df:
        df["source"] = "kaggle"
    if args.extra:
        df = pd.concat([df, pd.read_csv(args.extra)], ignore_index=True)
    df = df[df["material"].isin(MATERIALS)].reset_index(drop=True)
    y = df["material"].map({m: i for i, m in enumerate(MATERIALS)}).to_numpy()
    print(df.pivot_table(index=["source", "material"], columns="split", values="path", aggfunc="count", fill_value=0))

    base = tf.keras.applications.EfficientNetB0(include_top=False, weights="imagenet", pooling="avg",
                                                input_shape=(IMG_SIZE, IMG_SIZE, 3))
    base.trainable = False
    cache_dir = ROOT / "data" / "cache"
    idx = {s: np.where(df["split"] == s)[0] for s in ["train", "val", "test"]}
    # Las fotos reales de Clean Lab pesan más: se repiten en entrenamiento
    cl = idx["train"][(df.loc[idx["train"], "source"] == "cleanlab").to_numpy()]
    idx["train"] = np.concatenate([idx["train"]] + [cl] * (args.extra_weight - 1)) if len(cl) else idx["train"]

    feats = {}
    for split in ["train", "val", "test"]:
        uniq = np.unique(idx[split])
        print(f"Calculando características de {len(uniq)} fotos ({split})…")
        key = hashlib.md5("|".join(df.loc[uniq, "path"]).encode()).hexdigest()[:12]
        x = embed(base, df.loc[uniq, "path"], cache_dir / f"{split}_{key}.npz")
        pos = {i: k for k, i in enumerate(uniq)}
        feats[split] = x[[pos[i] for i in idx[split]]]

    y_tr, y_va, y_te = y[idx["train"]], y[idx["val"]], y[idx["test"]]
    counts = np.bincount(y_tr, minlength=len(MATERIALS))
    class_weight = {i: len(y_tr) / (len(MATERIALS) * c) for i, c in enumerate(counts) if c > 0}

    # Etapa 1: solo la capa final
    head = tf.keras.Sequential([layers.Input(shape=(feats["train"].shape[1],)), layers.Dropout(0.3),
                                layers.Dense(len(MATERIALS), activation="softmax")], name="head")
    head.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    head.fit(feats["train"], y_tr, validation_data=(feats["val"], y_va), epochs=args.epochs, batch_size=64,
             class_weight=class_weight, callbacks=[tf.keras.callbacks.EarlyStopping(patience=5, restore_best_weights=True)], verbose=2)
    pred = head.predict(feats["test"], verbose=0).argmax(1)
    metrics, confusion = evaluate(pred, y_te, idx["test"], df, y_tr)
    print(f"\n[Etapa 1] acierto en prueba: {metrics['test_accuracy']:.1%} · baseline: {metrics['baseline_accuracy']:.1%}")
    print(f"Por material: { {k: f'{v:.0%}' for k, v in metrics['accuracy_por_material'].items()} }")

    # Modelo completo: imagen → (augmentation solo al entrenar) → red base → capa final
    augment = tf.keras.Sequential([layers.RandomFlip("horizontal"), layers.RandomRotation(0.05),
                                   layers.RandomZoom(0.1), layers.RandomContrast(0.15)], name="augmentation")
    inputs = layers.Input(shape=(IMG_SIZE, IMG_SIZE, 3))
    model = tf.keras.Model(inputs, head(base(augment(inputs), training=False)), name="sneaker_doctor")

    if args.finetune_epochs > 0:
        # Etapa 2: fine-tuning de las últimas capas (las BatchNorm se mantienen congeladas)
        base.trainable = True
        for layer in base.layers[:-args.finetune_layers]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, layers.BatchNormalization):
                layer.trainable = False

        def dataset(ix, shuffle):
            paths, labels = df.loc[ix, "path"].to_numpy(), y[ix]
            def gen():
                order = np.random.permutation(len(ix)) if shuffle else np.arange(len(ix))
                for k in order:
                    yield preprocess(Image.open(paths[k]))[0], labels[k]
            sig = (tf.TensorSpec((IMG_SIZE, IMG_SIZE, 3), tf.float32), tf.TensorSpec((), tf.int64))
            return tf.data.Dataset.from_generator(gen, output_signature=sig).batch(32).prefetch(tf.data.AUTOTUNE)

        model.compile(optimizer=tf.keras.optimizers.Adam(1e-5), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
        model.fit(dataset(idx["train"], True), validation_data=dataset(idx["val"], False), epochs=args.finetune_epochs,
                  class_weight=class_weight, callbacks=[tf.keras.callbacks.EarlyStopping(patience=2, restore_best_weights=True)], verbose=2)
        pred = model.predict(dataset(idx["test"], False), verbose=0).argmax(1)
        metrics, confusion = evaluate(pred, y_te, idx["test"], df, y_tr)
        metrics["finetune"] = {"epochs": args.finetune_epochs, "layers": args.finetune_layers}
        print(f"\n[Etapa 2 · fine-tuning] acierto en prueba: {metrics['test_accuracy']:.1%}")

    print(f"Por fuente: { {k: f'{v:.0%}' for k, v in metrics['accuracy_por_fuente'].items()} }")
    print(f"Por material: { {k: f'{v:.0%}' for k, v in metrics['accuracy_por_material'].items()} }")
    print(confusion)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "sneaker_doctor.keras")
    (out / "labels.json").write_text(json.dumps(MATERIALS), encoding="utf-8")
    metrics.update({"n_train": int(len(y_tr)), "n_test": int(len(y_te))})
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    wrong = pred != y_te
    df.loc[idx["test"][wrong], ["path", "material", "source"]].assign(
        predicho=[MATERIALS[i] for i in pred[wrong]]).to_csv(out / "errores_prueba.csv", index=False)
    print(f"\nModelo guardado en {out / 'sneaker_doctor.keras'} · errores en {out / 'errores_prueba.csv'}")


if __name__ == "__main__":
    main()
