// Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
// SPDX-License-Identifier: GPL-2.0-only

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/errno.h>
#include <linux/blkdev.h>
#include <linux/blk-mq.h>
#include <linux/highmem.h>
#include <linux/numa.h>
#include <linux/of.h>
#include <linux/of_address.h>

#define DRV_NAME "ramcarveout"

/* Leave zero to auto-detect from the qcom,minidump-journal DTS node;
 * set non-zero on the modprobe command line to override.
 */
static u64 phys_addr;
module_param(phys_addr, ullong, 0444);
MODULE_PARM_DESC(phys_addr, "Carveout physical base address (0 = read from DTS)");

static unsigned int size_mb;
module_param(size_mb, uint, 0444);
MODULE_PARM_DESC(size_mb, "Carveout size in MB (0 = read from DTS)");

struct ramcarveout_dev {
	void __iomem *io;
	size_t size;

	int major;
	struct gendisk *disk;
	struct blk_mq_tag_set tag_set;
};

static struct ramcarveout_dev g_dev;

static blk_status_t ramcarveout_queue_rq(struct blk_mq_hw_ctx *hctx,
					const struct blk_mq_queue_data *bd)
{
	struct request *rq = bd->rq;
	struct ramcarveout_dev *dev = rq->q->queuedata;
	sector_t sector = blk_rq_pos(rq);
	loff_t off = (loff_t)sector << SECTOR_SHIFT;

	struct bio_vec bvec;
	struct req_iterator iter;
	unsigned int op;
	blk_status_t st = BLK_STS_OK;

	blk_mq_start_request(rq);

	op = req_op(rq);
	if (op != REQ_OP_READ && op != REQ_OP_WRITE) {
		st = BLK_STS_NOTSUPP;
		goto out_end;
	}

	if (sector >= (dev->size >> SECTOR_SHIFT)) {
		blk_mq_end_request(rq, BLK_STS_IOERR);
		return BLK_STS_OK;
	}

	rq_for_each_segment(bvec, rq, iter) {
		void *base;
		size_t len = bvec.bv_len;

		if (off + len > dev->size) {
			st = BLK_STS_IOERR;
			break;
		}

		base = kmap_local_page(bvec.bv_page);

		if (op == REQ_OP_WRITE)
			memcpy_toio(dev->io + off, base + bvec.bv_offset, len);
		else
			memcpy_fromio(base + bvec.bv_offset, dev->io + off, len);

		kunmap_local(base);
		off += len;
	}

out_end:
	blk_mq_end_request(rq, st);
	return BLK_STS_OK;
}

static const struct blk_mq_ops ramcarveout_mq_ops = {
	.queue_rq = ramcarveout_queue_rq,
};

static const struct block_device_operations ramcarveout_fops = {
	.owner = THIS_MODULE,
};

static int __init ramcarveout_init(void)
{
	int ret;
	struct ramcarveout_dev *dev = &g_dev;

	/*
	 * Read phys_addr/size_mb from the same DTS node that minidump_log.c
	 * uses (qcom,minidump-journal), so the two are always in sync.
	 */
	if (!phys_addr || !size_mb) {
		struct device_node *np;
		struct resource res;

		np = of_find_compatible_node(NULL, NULL, "qcom,minidump-journal");
		if (np) {
			if (of_address_to_resource(np, 0, &res) == 0) {
				if (!phys_addr)
					phys_addr = res.start;
				if (!size_mb)
					size_mb = (unsigned int)(resource_size(&res) >> 20);
			} else {
				pr_err(DRV_NAME ": of_address_to_resource failed\n");
			}
			of_node_put(np);
		} else {
			pr_err(DRV_NAME ": qcom,minidump-journal DTS node not found\n");
		}
	}

	if (!phys_addr) {
		pr_err(DRV_NAME ": phys_addr not set\n");
		return -EINVAL;
	}
	if (!size_mb) {
		pr_err(DRV_NAME ": size_mb not set\n");
		return -EINVAL;
	}

	memset(dev, 0, sizeof(*dev));
	dev->size = (size_t)size_mb * 1024 * 1024;

	dev->io = ioremap((phys_addr_t)phys_addr, dev->size);
	if (!dev->io)
		return -ENOMEM;

	dev->major = register_blkdev(0, DRV_NAME);
	if (dev->major < 0) {
		ret = dev->major;
		goto err_unmap;
	}

	memset(&dev->tag_set, 0, sizeof(dev->tag_set));
	dev->tag_set.ops = &ramcarveout_mq_ops;
	dev->tag_set.nr_hw_queues = 1;
	dev->tag_set.queue_depth = 128;
	dev->tag_set.numa_node = NUMA_NO_NODE;
	dev->tag_set.cmd_size = 0;
	dev->tag_set.flags = BLK_MQ_F_SHOULD_MERGE;
	dev->tag_set.driver_data = dev;

	ret = blk_mq_alloc_tag_set(&dev->tag_set);
	if (ret)
		goto err_unreg_blkdev;

	dev->disk = blk_mq_alloc_disk(&dev->tag_set, dev);
	if (IS_ERR(dev->disk)) {
		ret = PTR_ERR(dev->disk);
		dev->disk = NULL;
		goto err_free_tagset;
	}

	dev->disk->major = dev->major;
	dev->disk->first_minor = 0;
	dev->disk->minors = 1;
	dev->disk->fops = &ramcarveout_fops;
	dev->disk->private_data = dev;
	snprintf(dev->disk->disk_name, DISK_NAME_LEN, DRV_NAME);

	set_capacity(dev->disk, dev->size >> SECTOR_SHIFT);

	ret = add_disk(dev->disk);
	if (ret)
		goto err_put_disk;

	pr_info(DRV_NAME ": mapped phys=0x%llx size=%uMB major=%d\n",
		phys_addr, size_mb, dev->major);
	return 0;

err_put_disk:
	del_gendisk(dev->disk);
	blk_mq_free_tag_set(&dev->tag_set);
	put_disk(dev->disk);
	dev->disk = NULL;
	unregister_blkdev(dev->major, DRV_NAME);
	iounmap(dev->io);
	return ret;

err_free_tagset:
	blk_mq_free_tag_set(&dev->tag_set);
err_unreg_blkdev:
	unregister_blkdev(dev->major, DRV_NAME);
err_unmap:
	iounmap(dev->io);
	return ret;
}

static void __exit ramcarveout_exit(void)
{
	struct ramcarveout_dev *dev = &g_dev;

	if (dev->disk) {
		del_gendisk(dev->disk);
		blk_mq_free_tag_set(&dev->tag_set);
		put_disk(dev->disk);
		dev->disk = NULL;
	}

	if (dev->major > 0)
		unregister_blkdev(dev->major, DRV_NAME);

	if (dev->io)
		iounmap(dev->io);

	pr_info(DRV_NAME ": unloaded\n");
}

module_init(ramcarveout_init);
module_exit(ramcarveout_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Qualcomm");
MODULE_DESCRIPTION("Minimal carveout-backed block device using blk-mq");
