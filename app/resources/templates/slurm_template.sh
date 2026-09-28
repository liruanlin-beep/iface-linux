#!/bin/bash
#SBATCH -J {job_name}
#SBATCH -p {partition}
#SBATCH -N {nodes}
#SBATCH --ntasks-per-node={ntasks_per_node}
#SBATCH -t {time}
#SBATCH -o slurm-%j.out
#SBATCH -e slurm-%j.err

module purge
module load vasp

{vasp_command}
