from app import config, db, logger
from app.models import Post
from podcast_processor.podcast_processor import PodcastProcessor
from shared.podcast_downloader import download_episode


def download_and_process_post(p_guid: str, blocking: bool = True) -> str:
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        raise PostException(f"Post with GUID: {p_guid} not found")

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        raise PostException(f"Post with GUID: {p_guid} not whitelisted")

    logger.info(f"Downloading post: {post.title}")

    # Download the episode
    download_path = download_episode(post)

    if download_path is None:
        raise PostException("Download failed")

    post.unprocessed_audio_path = download_path
    db.session.commit()

    # Process the episode
    processor = PodcastProcessor(config)
    output_path = processor.process(post, blocking)
    if output_path is None:
        raise PostException("Processing failed")
    return output_path


class PostException(Exception):
    pass
