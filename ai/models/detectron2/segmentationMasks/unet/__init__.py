'''
    Detectron2-compliant adaptation of the following U-net implementation:
    https://github.com/milesial/Pytorch-UNet

    2022 Benjamin Kellenberger
'''

# default options for the model, may be overridden in the custom configuration loaded at runtime
DEFAULT_OPTIONS = {
	"defs": {
		"transforms": {
			"RandomBrightness": {
				"name": "Random brightness",
				"description": "Randomly transforms image brightness.<br />Brightness intensity is uniformly sampled in (intensity_min, intensity_max). - intensity < 1 will reduce brightness - intensity = 1 will preserve the input image - intensity > 1 will increase brightness.<br />See <a href=\"https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html\" target=\"_blank\">https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html</a>.",
				"intensity_min": {
					"name": "Min",
					"min": 0,
					"max": 1,
					"value": 0.0
				},
				"intensity_max": {
					"name": "Max",
					"min": 0,
					"max": 1,
					"value": 1.0
				}
			},
			"RandomContrast": {
				"name": "Random contrast",
				"description": "Randomly transforms image contrast.<br />Contrast intensity is uniformly sampled in (intensity_min, intensity_max). - intensity < 1 will reduce contrast - intensity = 1 will preserve the input image - intensity > 1 will increase contrast<br />See <a href=\"https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html\" target=\"_blank\">https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html</a>.",
				"intensity_min": {
					"name": "Min",
					"min": 0,
					"max": 1,
					"value": 0.0
				},
				"intensity_max": {
					"name": "Max",
					"min": 0,
					"max": 1,
					"value": 1.0
				}
			},
			"RandomSaturation": {
				"name": "Random saturation",
				"description": "Randomly transforms saturation of an RGB image.<br />Saturation intensity is uniformly sampled in (intensity_min, intensity_max). - intensity < 1 will reduce saturation (make the image more grayscale) - intensity = 1 will preserve the input image - intensity > 1 will increase saturation<br />See <a href=\"https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html\" target=\"_blank\">https://pillow.readthedocs.io/en/3.0.x/reference/ImageEnhance.html</a>.",
				"intensity_min": {
					"name": "Min",
					"min": 0,
					"max": 1,
					"value": 0.0
				},
				"intensity_max": {
					"name": "Max",
					"min": 0,
					"max": 1,
					"value": 1.0
				}
			},
			"RandomLighting": {
				"name": "Random lighting",
				"description": "The \"lighting\" augmentation described in <a href=\"https://doi.org/10.1145/3065386\" target=\"_blank\">AlexNet</a>, using fixed PCA over ImageNet.<br />The degree of color jittering is randomly sampled via a normal distribution, with standard deviation given by the scale parameter.",
				"scale": {
					"name": "Scale",
					"description": "Standard deviation of principal component weighting.",
					"min": -1e9,
					"max": 1e9,
					"value": 0.0
				}
			},
			"RandomFlip": {
				"name": "Random flip",
				"description": "Randomly flips the image in horizontal and/or vertical direction with the given probability.",
				"prob": {
					"name": "Probability",
					"min": 0,
					"max": 1,
					"value": 0.5
				},
				"horizontal": {
					"name": "Horizontal",
					"value": True
				},
				"vertical": {
					"name": "Vertical",
					"value": False
				}
			},
			"RandomRotation": {
				"name": "Random rotation",
				"description": "Randomly rotates the image counterclockwise around the center.",
				"angle": {
					"name": "Angles",
					"description": "A list of angles to randomly choose from, if \"Sample style\" is 'choice'. If it is 'range', the smallest and largest values of the list will be chosen as [min, max] accordingly.",
					"type": "list",
					"options": [
						{
							"name": "Value",
							"min": -360,
							"max": 360,
							"value": 0
						}
					],
					"value": [
						{
							"value": -270
						},
						{
							"value": 270
						}
					]
				},
				"expand": {
					"name": "Expand image",
					"description": "Choose if the image should be resized to fit the whole rotated image (ticked; default), or simply cropped (unticked).",
					"value": True
				}
			},
			"RandomCrop": {
				"name": "Random crop",
				"description": "Randomly crops a patch out of an image.",
				"crop_type": {
					"name": "Cropping type",
					"type": "select",
					"options": {
						"relative_range": {
							"name": "relative (range)"
						},
						"relative": {
							"name": "relative"
						},
						"absolute" : {
							"name": "absolute"
						},
						"absolute_range": {
							"name": "absolute (range)"
						}
					},
					"value": "relative"
				},
				"crop_size": {
					"name": "Cropping size",
					"description": "Enter relative values [0, 1] if a \"relative\" cropping type has been chosen, or absolute pixel values otherwise.",
					"type": "list",
					"value": [
						{
							"name": "height",
							"min": 0,
							"max": 1e9,
							"value": 1.0
						},
						{
							"name": "width",
							"min": 0,
							"max": 1e9,
							"value": 1.0
						}
					]
				}
			},
			"Resize": {
				"name": "Resize",
				"description": "Resizes the input image to a fixed target size.",
				"shape": {
					"name": "Output size",
					"type": "list",
					"value": [
						{
							"name": "Height",
							"min": 0,
							"max": 1e9,
							"value": 512
						},
						{
							"name": "Width",
							"min": 0,
							"max": 1e9,
							"value": 1024
						}
					]
				},
				"interp": {
					"name": "Interpolation method",
					"type": "select",
					"options": {
						"0": {
							"name": "Nearest neighbor"
						},
						"2": {
							"name": "Bilinear interpolation"
						},
						"3": {
							"name": "Bicubic"
						},
						"5": {
							"name": "Hamming"
						},
						"6": {
							"name": "Lanczos"
						}
					},
					"value": 0
				}
			}
		}
	},
	"options": {
		"general": {
			"name": "General options",
			"DETECTRON2.MODEL.DEVICE": {
				"name": "Device",
				"type": "select",
				"options": {
					"cpu": {
						"name": "CPU",
						"description": "Run U-net on the CPU and with system RAM."
					},
					"cuda": {
						"name": "GPU",
						"description": "Requires a <a href=\"https://developer.nvidia.com/cuda-zone\" target=\"_blank\">CUDA-enabled</a> graphics card."
					}
				},
				"value": "cuda",
				"style": {
					"inline": True
				}
			},
			"DETECTRON2.SEED": {
				"name": "Random seed",
				"type": "int",
				"min": -1e9,
				"max": 1e9,
				"value": -1
			},
			"labelClasses": {
				"name": "New and removed label classes",
				"add_missing": {
					"name": "Add new label classes",
					"description": "If checked, neurons for newly added label classes will be added to the model.<br />Note that these new classes need extra training.",
					"value": True
				},
				"remove_obsolete": {
					"name": "Remove obsolete label classes",
					"description": "If checked, neurons from label classes not present in this project will be removed during next model training.",
					"value": False
				}
			}
		},
		"model": {
			"name": "Model options",
			"description": "Choose a pre-trained starting point.<br />If your project already contains at least one model state, this choice is ignored unless \"Force new model\" is ticked, in which case a completely new model is being built.",
			"config": {
				"name": "Pre-made configuration",
				"description": "Choose a pre-trained model state here or create your own model from scratch (\"manual\").",
				"type": "select",
				"value": "segmentationMasks/unet/base-unet.yaml",
				"options": {
					"segmentationMasks/unet/base-unet.yaml": {
						"name": "Basic untrained U-net"
					}
				}
			},
			"force": {
				"name": "Force new model",
				"value": False
			}
		},
		"train": {
			"name": "Training options",
			"dataLoader": {
				"name": "Data loader options",
				"DETECTRON2.SOLVER.IMS_PER_BATCH": {
					"name": "Batch size",
					"description": "Number of images to train on at a time (in chunks). Reduce number in case of out-of-memory issues.",
					"min": 1,
					"max": 8192,
					"value": 1
				}
			},
			"optim": {
				"name": "Optimizer",
				"DETECTRON2.SOLVER.BASE_LR": {
					"name": "Base learning rate",
					"min": 0.0,
					"max": 100.0,
					"value": 0.01
				},
				"DETECTRON2.SOLVER.BIAS_LR_FACTOR": {
					"name": "Biasing factor for learning rate",
					"min": 0.0,
					"max": 100.0,
					"value": 1.0
				},
				"DETECTRON2.SOLVER.WEIGHT_DECAY": {
					"name": "Weight decay",
					"min": 0.0,
					"max": 100.0,
					"value": 0.001
				},
				"DETECTRON2.SOLVER.WEIGHT_DECAY_BIAS": {
					"name": "Biasing factor for weight decay",
					"min": 0.0,
					"max": 100.0,
					"value": 0.0001
				},
				"DETECTRON2.SOLVER.WEIGHT_DECAY_NORM": {
					"name": "Weight decay normalization factor",
					"min": 0.0,
					"max": 100.0,
					"value": 0.0
				},
				"DETECTRON2.SOLVER.GAMMA": {
					"name": "Gamma",
					"min": 0.0,
					"max": 100.0,
					"value": 0.1
				},
				"DETECTRON2.SOLVER.MOMENTUM": {
					"name": "Enable momentum",
					"value": False	
				},
				"DETECTRON2.SOLVER.NESTEROV": {
					"name": "Enable Nesterov momentum",
					"value": False
				},
				"clip_gradients": {
					"DETECTRON2.SOLVER.CLIP_GRADIENTS.ENABLED": {
						"name": "Enable gradient clipping",
						"value": False
					},
					"DETECTRON2.SOLVER.CLIP_GRADIENTS.CLIP_VALUE": {
						"name": "Clip value",
						"min": 0.0,
						"max": 100.0,
						"value": 1.0
					},
					"DETECTRON2.SOLVER.CLIP_GRADIENTS.NORM_TYPE": {
						"name": "Type of gradient norm to calculate",
						"min": 0.0,
						"max": 100.0,
						"value": 2.0
					}
				}
			},
			"transform": {
				"name": "Transforms",
				"description": "Transforms are used to prepare images as inputs for the model, as well as to perform data augmentation.",
				"type": "list",
				"options": "transforms",
				"value": [
					"Resize",
					"RandomFlip",
					"RandomLighting",
					"RandomContrast",
					"RandomSaturation"
				]
			},
			"ignore_unsure": {
				"name": "Ignore (discard) annotations marked as \"unsure\"",
				"value": True
			}
		},
		"inference": {
			"name": "Inference (prediction) options",
			"transform": {
				"name": "Transforms",
				"description": "Transforms to apply during inference time.",
				"type": "list",
				"options": "transforms",
				"value": [
					"Resize"
				]
			}
		}
	}
}