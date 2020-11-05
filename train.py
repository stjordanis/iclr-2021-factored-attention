from argparse import ArgumentParser
import matplotlib.pyplot as plt
from pathlib import Path
import pytorch_lightning as pl
import random
import string
import torch
import wandb


from mogwai.data_loading import MSADataModule
from mogwai.parsing import read_contacts
from mogwai import models
from mogwai.utils.functional import apc
from mogwai.metrics import contact_auc
from mogwai.plotting import (
    plot_colored_preds_on_trues,
    plot_precision_vs_length,
)
from mogwai.vocab import FastaVocab


def train():
    # Initialize parser
    parser = ArgumentParser()
    parser.add_argument(
        "--model",
        default="gremlin",
        choices=models.MODELS.keys(),
        help="Which model to train.",
    )
    model_name = parser.parse_known_args()[0].model
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Optional file to output gremlin weights.",
    )
    parser.add_argument(
        "--wandb_project",
        type=str,
        default="gremlin-contacts",
        help="W&B project used for logging.",
    )
    parser = MSADataModule.add_args(parser)
    parser = pl.Trainer.add_argparse_args(parser)
    parser.set_defaults(
        gpus=1,
        min_steps=50,
        max_steps=1000,
    )
    model_type = models.get(model_name)
    model_type.add_args(parser)
    args = parser.parse_args()

    # Modify name
    pdb = args.data
    args.data = "data/npz/" + args.data + ".npz"
    print(args.data)

    # Load msa
    msa_dm = MSADataModule.from_args(args)
    msa_dm.setup()

    # Load contacts
    true_contacts = torch.from_numpy(read_contacts(args.data))

    # Initialize model
    num_seqs, msa_length, msa_counts = msa_dm.get_stats()
    model = model_type.from_args(
        args,
        num_seqs=num_seqs,
        msa_length=msa_length,
        msa_counts=msa_counts,
        vocab_size=len(FastaVocab),
        pad_idx=FastaVocab.pad_idx,
        true_contacts=true_contacts,
    )

    kwargs = {}
    randstring = "".join(random.choice(string.ascii_lowercase) for i in range(6))
    run_name = "_".join([args.model, pdb, randstring])
    logger = pl.loggers.WandbLogger(project=args.wandb_project, name=run_name)
    logger.log_hyperparams(args)
    logger.log_hyperparams(
        {
            "pdb": Path(args.data).stem,
            "num_seqs": num_seqs,
            "msa_length": msa_length,
        }
    )
    kwargs["logger"] = logger

    # Initialize Trainer
    trainer = pl.Trainer.from_argparse_args(args, **kwargs)

    trainer.fit(model, msa_dm)

    # Log and print some metrics after training.
    contacts = model.get_contacts()
    auc = contact_auc(contacts, true_contacts).item()
    contacts = apc(contacts)
    auc_apc = contact_auc(contacts, true_contacts).item()
    print(f"AUC: {auc:0.3f}, AUC_APC: {auc_apc:0.3f}")

    filename = "top_L_contacts.png"
    plot_colored_preds_on_trues(contacts, true_contacts, point_size=5)
    logger.log_metrics({filename: wandb.Image(plt)})
    plt.close()

    filename = "top_L_contacts_apc.png"
    plot_colored_preds_on_trues(apc(contacts), true_contacts, point_size=5)
    logger.log_metrics({filename: wandb.Image(plt)})
    plt.close()

    filename = "precision_vs_L.png"
    plot_precision_vs_length(contacts, true_contacts)
    logger.log_metrics({filename: wandb.Image(plt)})
    plt.close()

    if args.output_file is not None:
        torch.save(model.state_dict(), args.output_file)


if __name__ == "__main__":
    train()
